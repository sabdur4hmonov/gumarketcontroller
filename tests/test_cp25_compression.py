"""Real compressed bytes and HTTP negotiation, with bounded public inputs."""

import gzip

import brotli
from aiohttp.test_utils import TestClient, TestServer
from scripts.compress_static import compress
from tests.test_cp25_web_cache import app

from gulbot.web import render


async def test_static_brotli_gzip_roundtrip_and_content_negotiation(tmp_path, monkeypatch):
    directory = tmp_path / "css"
    directory.mkdir()
    asset = directory / "test.css"
    raw = b".flower{color:gold;background:green}" * 500
    asset.write_bytes(raw)
    private = tmp_path / "customer.jpg"
    private.write_bytes(b"private")
    sizes = compress(tmp_path)
    assert len(sizes) == 1 and sizes[0]["raw"] == len(raw)
    assert brotli.decompress(asset.with_suffix(".css.br").read_bytes()) == raw
    assert gzip.decompress(asset.with_suffix(".css.gz").read_bytes()) == raw
    assert not private.with_suffix(".jpg.br").exists(), (
        "Private images must not be compressed by the static builder"
    )
    monkeypatch.setattr(render, "STATIC", tmp_path)
    render._static_version.cache_clear()
    async with TestClient(TestServer(app()), auto_decompress=False) as client:
        for encoding, decode in (("br", brotli.decompress), ("gzip", gzip.decompress)):
            response = await client.get(
                render.static_url("css/test.css"), headers={"Accept-Encoding": encoding}
            )
            assert response.status == 200
            assert response.headers["Content-Encoding"] == encoding
            assert decode(await response.read()) == raw
            assert "Accept-Encoding" in response.headers["Vary"]
            assert "immutable" in response.headers["Cache-Control"]
            assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    render._static_version.cache_clear()


def test_compression_rejects_large_inputs_before_creating_sidecars(tmp_path):
    (tmp_path / "large.css").write_bytes(b"x" * 1_048_577)
    rejected = False
    try:
        compress(tmp_path)
    except ValueError:
        rejected = True
    assert rejected and not (tmp_path / "large.css.br").exists()


def test_compression_will_not_follow_a_sidecar_symlink(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "asset.css"
    output = tmp_path / "asset.css.gz"
    source.write_bytes(b"body{}")
    output.write_bytes(b"outside sentinel")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == output or original(path))
    rejected = False
    try:
        compress(tmp_path)
    except ValueError:
        rejected = True
    assert rejected and output.read_bytes() == b"outside sentinel"


def test_compression_checks_resolved_root_before_reading_input(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "asset.css"
    source.write_bytes(b"body{}")
    original = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **k: (
            tmp_path.parent / "foreign.css" if path == source else original(path, *a, **k)
        ),
    )
    rejected = False
    try:
        compress(tmp_path)
    except ValueError:
        rejected = True
    assert rejected and not source.with_suffix(".css.br").exists()


def test_compression_refuses_a_symlink_temporary_output(tmp_path, monkeypatch):
    from pathlib import Path

    source = tmp_path / "asset.css"
    temporary = tmp_path / "asset.css.gz.tmp"
    source.write_bytes(b"body{}")
    temporary.write_bytes(b"outside sentinel")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == temporary or original(path))
    rejected = False
    try:
        compress(tmp_path)
    except ValueError:
        rejected = True
    assert rejected and temporary.read_bytes() == b"outside sentinel"
