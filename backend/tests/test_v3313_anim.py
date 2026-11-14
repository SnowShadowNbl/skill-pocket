"""v3.3.13 SVG 封面动图：SMIL 逐帧求值、/media/anim/... 生成动图 WebP、静态 SVG / 位图 404。"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app
from app.services import anim

ANIM = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#eef3fb"/>'
        '<rect x="100" y="300" height="40" width="100" fill="#1E56D6">'
        '<animate attributeName="width" values="100;900;100" dur="4s" repeatCount="indefinite"/></rect>'
        '<g transform="translate(10 0)"><circle cx="640" cy="200" r="40" fill="#1E56D6">'
        '<animateTransform attributeName="transform" type="translate" values="0 0;0 -60;0 0" dur="2s" begin="0.5s" repeatCount="indefinite"/>'
        '</circle></g></svg>')
STATIC = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#eee"/></svg>'


@pytest.fixture(autouse=True)
def tmp_media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", tmp_path)
    (tmp_path / "covers").mkdir()


def _write(name: str, text: str) -> str:
    (settings.media_dir / "covers" / name).write_text(text, encoding="utf-8")
    return f"covers/{name}"


def test_anim_url_only_for_svg():
    assert anim.anim_url("covers/a.svg") == "/media/anim/covers/a.svg.webp"
    assert anim.anim_url("covers/a.png") is None and anim.anim_url("") is None


def test_smil_values():
    sc = anim.Scene(ANIM)
    assert len(sc.anims) == 2 and "<animate" not in sc.frame(0)
    assert sc.period() == 4.0
    assert 'width="500"' in sc.frame(1.0)  # 4 秒里第 1 秒：100 → 900 走了一半
    assert 'translate(0 -30)' in sc.frame(1.0)  # begin 0.5s，2 秒一圈，第 0.5 秒在一半上升途中
    assert 'transform' not in sc.frame(0.2).split("<circle")[1].split(">")[0]  # 还没开始：保持原样


def _wait(rel: str, timeout: float = 60) -> None:
    import time
    end = time.time() + timeout
    while time.time() < end:
        if anim.pending() == 0 and rel not in anim._queued:
            return
        time.sleep(0.1)
    raise AssertionError('后台队列没跑完')


def test_anim_endpoint_never_waits():
    """v3.3.14 还没生成时立刻 404（no-store）并排队，后台生成好之后再请求就是动图。"""
    c = TestClient(app)
    p = _write('a-ai-1.svg', ANIM)
    r = c.get(anim.anim_url(p))
    assert r.status_code == 404 and r.headers['cache-control'] == 'no-store'
    _wait(p)
    r = c.get(anim.anim_url(p))
    assert r.status_code == 200 and r.headers['content-type'] == 'image/webp'
    im = Image.open(io.BytesIO(r.content))
    assert im.size == (640, 360) and im.n_frames >= 30 and len(r.content) <= anim.MAX_BYTES
    assert (settings.media_dir / 'thumb' / f'{p}.jpg').is_file()  # 顺带生成了缩略图

    s = _write('s-ai-2.svg', STATIC)
    assert c.get(anim.anim_url(s)).status_code == 404
    _wait(s)
    r = c.get(anim.anim_url(s))  # 没有动画：记住了，可以缓存
    assert r.status_code == 404 and 'max-age' in r.headers['cache-control']
    assert c.get('/media/anim/covers/x.png.webp').status_code == 404
    assert c.get('/media/anim/covers/..%2F..%2Fapp.db.svg.webp').status_code == 404


def test_cover_change_enqueues(monkeypatch):
    from app.models import Item
    got = []
    monkeypatch.setattr(anim, 'enqueue', lambda p, front=False: got.append(p))
    it = Item(name='x')
    it.cover_path = 'covers/9-ai-new.svg'
    it.cover_path = 'covers/9-ai-new.svg'  # 没变不重复排队
    assert got == ['covers/9-ai-new.svg']
