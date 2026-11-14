"""v3.3.12 封面缩略图：接口带 cover_thumb_url，/media/thumb/... 现场生成 JPEG，非法路径 404。"""

import io

import pytest

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app
from app.schemas import item_card
from app.services import compare, thumbs

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><defs><linearGradient id="g">'
       '<stop offset="0" stop-color="#1E56D6"/><stop offset="1" stop-color="#fff"/></linearGradient></defs>'
       '<rect width="1280" height="720" fill="url(#g)"/><circle cx="640" cy="360" r="100" fill="url(#dots)">'
       '<animate attributeName="r" values="100;140;100" dur="3s" repeatCount="indefinite"/></circle></svg>')


@pytest.fixture(autouse=True)
def tmp_media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", tmp_path)


def _write(name: str, data: bytes) -> str:
    d = settings.media_dir / "covers"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    return f"covers/{name}"


def test_thumb_url_shape():
    assert thumbs.thumb_url("covers/a.svg") == "/media/thumb/covers/a.svg.jpg"
    assert thumbs.thumb_url("") is None and thumbs.thumb_url(None) is None


def test_svg_and_png_thumbs():
    c = TestClient(app)
    svg = _write("t-ai-1.svg", SVG.encode())
    r = c.get(thumbs.thumb_url(svg))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "JPEG" and im.size == (640, 360)

    buf = io.BytesIO()
    Image.new("RGBA", (2000, 1000), (30, 86, 214, 128)).save(buf, "PNG")
    png = _write("t-2.png", buf.getvalue())
    r = c.get(thumbs.thumb_url(png))
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (640, 320)
    assert (settings.media_dir / "thumb" / f"{png}.jpg").is_file()  # 第二次直接读文件
    assert c.get(thumbs.thumb_url(png)).content == r.content


def test_bad_paths_404():
    c = TestClient(app)
    for p in ("/media/thumb/covers/nope.svg.jpg", "/media/thumb/covers/t-2.png", "/media/thumb/avatars/x.png.jpg",
              "/media/thumb/covers/..%2F..%2Fapp.db.jpg"):
        assert c.get(p).status_code == 404, p
    bad = _write("t-bad.svg", b"<svg not really")
    assert c.get(thumbs.thumb_url(bad)).status_code == 404


def test_old_compare_subject_gets_thumb():
    assert compare.subject_thumb({"cover_url": "/media/covers/x.svg"}) == "/media/thumb/covers/x.svg.jpg"
    assert compare.subject_thumb({"cover_url": ""}) is None
