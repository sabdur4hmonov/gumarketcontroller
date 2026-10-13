"""Real service boundaries offload byte work; database/session stays on loop."""

from __future__ import annotations

import io
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from gulbot.announcements.extraction import Fields
from gulbot.bot.routers import announcements as router
from gulbot.models.announcement import AnnouncementDraft, ShopLogo
from gulbot.models.share_page import SharePage
from gulbot.services import announcements, share_page_photos, shop_logo


async def test_photo_cleaning_is_off_loop_but_session_writes_are_on_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    computation, writes = [], []
    page = SharePage(id=1, shop_id=1, customer_id=1, kind="yesno")
    monkeypatch.setattr(share_page_photos, "_own_open_page", AsyncMock(return_value=page))
    monkeypatch.setattr(share_page_photos.premium, "require", AsyncMock())

    def clean(raw):
        computation.append(threading.get_ident())
        return share_page_photos.CleanPhoto(b"jpeg", 16, 16)

    monkeypatch.setattr(share_page_photos, "clean_photo", clean)
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[]),
        execute=AsyncMock(),
        add=lambda row: writes.append(threading.get_ident()),
        flush=AsyncMock(),
    )
    await share_page_photos.store_photo(session, shop_id=1, customer_id=1, page_id=1, raw=b"image")
    assert computation and all(t != loop_thread for t in computation), (
        "Pillow must not block bot loop"
    )
    assert writes == [loop_thread], "AsyncSession cannot cross threads"


async def test_logo_normalisation_and_decoding_are_off_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    normalising, decoding = [], []
    monkeypatch.setattr(shop_logo, "is_owner", AsyncMock(return_value=True))

    def normalise(raw):
        normalising.append(threading.get_ident())
        return b"png", 32, 32

    monkeypatch.setattr(shop_logo, "normalise", normalise)
    session = SimpleNamespace(execute=AsyncMock(), get=AsyncMock(return_value=ShopLogo(shop_id=1)))
    await shop_logo.set_logo(session, shop_id=1, actor=1, data=b"image")
    output = io.BytesIO()
    Image.new("RGBA", (32, 32)).save(output, format="PNG")
    original = Image.open

    def opened(*args, **kwargs):
        decoding.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(shop_logo.Image, "open", opened)
    image = await shop_logo.logo_image(
        SimpleNamespace(scalar=AsyncMock(return_value=output.getvalue())), 1
    )
    assert image.size == (32, 32)
    assert normalising and normalising[0] != loop_thread, "Logo encode must be off loop"
    assert decoding and decoding[0] != loop_thread, "Logo decode must be off loop"


async def test_cold_spelling_extraction_is_off_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    seen = []

    def extract(*args, **kwargs):
        seen.append(threading.get_ident())
        return Fields(flowers=["atirgul"], count=1, price=1000)

    monkeypatch.setattr(announcements, "extract", extract)
    monkeypatch.setattr(
        announcements.announcement_learning, "learned_for", AsyncMock(return_value={})
    )
    monkeypatch.setattr(announcements.announcement_learning, "mark_used", AsyncMock())
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    draft = AnnouncementDraft(shop_id=1, status="draft", revision=1, preview_media=[])
    await announcements.parse_description(session, draft, "bir atirgul ming som")
    assert seen and seen[0] != loop_thread, "Dictionary I/O and spelling work must be off loop"
    assert draft.fields["price"] == 1000


async def test_legacy_overlay_is_off_loop(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    seen = []

    def overlay(*args, **kwargs):
        seen.append(threading.get_ident())
        return b"rendered-jpeg"

    async def download(file_id, destination):
        destination.write(b"photo")

    monkeypatch.setattr(router, "overlay", overlay)
    draft = AnnouncementDraft(
        id=1,
        shop_id=1,
        author_id=1,
        revision=1,
        status="confirmed",
        fields=Fields(flowers=["atirgul"], count=1, price=10000, colour="qizil").data(),
        photos=["cached"],
        template=None,
        logo_on=False,
        image_style="price",
        caption_style="classic",
    )
    bot = SimpleNamespace(
        download=download,
        send_photo=AsyncMock(
            return_value=SimpleNamespace(photo=[SimpleNamespace(file_id="cached-preview")])
        ),
    )
    message = SimpleNamespace(chat=SimpleNamespace(id=1), answer=AsyncMock())
    await router.exact_preview(
        bot, message, SimpleNamespace(scalar=AsyncMock(return_value="Shop")), draft
    )
    assert seen and seen[0] != loop_thread, "Legacy Pillow overlay must be off loop"
    assert draft.preview_media == ["cached-preview"]
