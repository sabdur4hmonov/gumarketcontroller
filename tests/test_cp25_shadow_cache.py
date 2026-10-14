"""Only tiny synthetic probes; full production matrices wait for RAM."""

from collections import Counter

from aiogram import Dispatcher, Router

from gulbot.bot import shadow_sweep as shadow


async def test_sweep_caches_source_metadata_but_evaluates_every_filter(monkeypatch):
    calls = Counter()
    locations = []

    async def first(message):
        pass

    async def second(message):
        pass

    async def always(message, raw_state=None):
        calls["always"] += 1
        return True

    async def conditional(message, raw_state=None):
        calls["conditional"] += 1
        return raw_state is None and message.text == "ping"

    dispatcher = Dispatcher()
    router = Router(name="tiny")
    router.message.register(first, always)
    router.message.register(second, conditional)
    dispatcher.include_router(router)
    monkeypatch.setattr(shadow, "declared_states", lambda: [None, "open"])
    monkeypatch.setattr(
        shadow,
        "probes",
        lambda: [
            ("message", "ping", shadow.make_message("ping")),
            ("message", "other", shadow.make_message("other")),
        ],
    )

    def location(callback):
        locations.append(callback.__name__)
        return callback.__name__

    monkeypatch.setattr(shadow, "_location", location)
    for iteration in (1, 2):
        found = await shadow.sweep(dispatcher)
        assert [(v.kind, v.state, v.trigger) for v in found] == [("DUPLICATE", "None", "ping")]
        assert calls == {"always": 4 * iteration, "conditional": 4 * iteration}
        assert locations == ["first", "second"] * iteration
