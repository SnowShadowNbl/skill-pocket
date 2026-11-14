from app.services.cover import sanitize_svg


def test_strips_scripts_events_and_external_refs():
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" onload="alert(1)" width="640">
      <script>alert(1)</script>
      <defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
      <rect width="640" height="360" fill="url(#g)" onclick="x()"/>
      <circle cx="10" cy="10" r="5" fill="url(http://evil.example/x.svg#a)"/>
      <foreignObject><div>hi</div></foreignObject>
      <image href="http://evil.example/x.png"/>
      <text>hello</text>
      <path d="M0 0L10 10" style="background:url(javascript:alert(1))"/>
    </svg>'''
    out = sanitize_svg(raw)
    assert out and out.startswith("<svg")
    for bad in ("script", "onload", "onclick", "foreignObject", "<image", "evil.example", "<text", "style=", "width=\"640\" xmlns"):
        assert bad not in out, bad
    assert 'fill="url(#g)"' in out
    assert "<circle" in out  # 元素保留，只删危险属性


def test_rejects_non_svg():
    assert sanitize_svg("no svg here") is None
    assert sanitize_svg("<svg><rect></svg") is None
