"""AI-3：没有截图的条目，由大模型画一张扁平风格的 SVG 示意图作封面（v3.0 起是蓝白主题，带 SMIL 缓动动画）。

DeepSeek 只输出文本，所以用“写 SVG 代码”代替文生图；保存前用白名单清洗，
去掉脚本、外链、事件属性，保证即使直接打开 SVG 文件也不会执行任何代码。
动画只允许 <animate> / <animateTransform>，且只能改几何、颜色、透明度这类展示属性（不能改 href 之类）。
以后要换真正的文生图接口，只需替换 generate_cover()。
"""

import hashlib
import re
import xml.etree.ElementTree as ET

from ..config import settings
from .extract import _chat_json

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

ALLOWED_TAGS = {
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "title", "animate", "animateTransform",
}
ANIM_TAGS = {"animate", "animateTransform"}
# 动画能改的属性
ANIMATABLE = {
    "opacity", "fill-opacity", "stroke-opacity", "fill", "stroke", "stroke-width", "stroke-dashoffset", "stroke-dasharray",
    "transform", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height", "d", "points",
    "offset", "stop-color", "stop-opacity",
}
ALLOWED_ATTRS = {
    "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-opacity",
    "stroke-dasharray", "opacity", "transform", "id", "offset", "stop-color", "stop-opacity", "gradientUnits",
    "gradientTransform", "clip-path", "mask", "preserveAspectRatio", "clip-rule", "stroke-dashoffset", "stroke-miterlimit",
    # 动画
    "attributeName", "attributeType", "type", "values", "from", "to", "by", "dur", "begin", "end", "repeatCount", "repeatDur",
    "keyTimes", "keySplines", "calcMode", "additive", "accumulate", "restart",
}
# 只允许引用本文件内的定义：url(#id)
_URL = re.compile(r"url\(\s*([^)]*)\)")

COVER_PROMPT = """你是 UI 插画设计师。为一个开源项目画一张 16:9 的封面插画（以 <img> 显示在网站卡片顶部），只输出 JSON：{"svg": "<svg ...>...</svg>"}
画面风格（网站是「蓝白索引台」主题：白底、细线、蓝色强调）：
- 根元素 <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360">，第一个元素是铺满的背景矩形，用 #F5F8FC → #EAF1FE 的竖向渐变或纯色 #EAF1FE
- 只用蓝白色系：主色 {fg}，辅助色 #1E56D6、#2F6BF0、#5AA2FF、#0B2F7A、#CFE0FF、#DCE4EF、#FFFFFF；不要出现紫、粉、橙、绿、红等其他色相
- 画成「产品界面线框 + 图标」的扁平示意图：圆角 6~10 的白色卡片 / 窗口 / 面板，1.5px 的 #DCE4EF 或主色细描边；背景可以加一层很淡的 28px 网格或点阵；主体略偏右，四周留白充足
- 用几何图形和图标式元素表达这个项目「是做什么的」（例如文档页、声波、对话气泡、齿轮、画笔、机器人、终端窗口、节点连线、图表、相机取景框）
- 层次：大面积浅色，主色只用在 1~2 个重点元素上，可以有一处 {fg} → #5AA2FF 的渐变高光
动效（用 SVG 自带的 SMIL 动画，必须有，但要克制、耐看）：
- 用 <animate> 或 <animateTransform> 给 3~6 个元素加循环动画，都写 repeatCount="indefinite"，dur 在 3s~12s 之间，各元素的 dur 或 begin 错开，避免同步
- 可选的动作：小幅上下漂浮（animateTransform type="translate"，位移 4~8）、呼吸式透明度（opacity 0.35↔1）、虚线流动（stroke-dashoffset）、齿轮或光环慢速旋转（type="rotate"，带旋转中心）、声波柱高度起伏、光标闪烁、进度条伸缩、节点脉冲（r 小幅变化）
- values 写成首尾相同的往返（例如 values="0 0;0 -6;0 0"），循环衔接不跳；不要大幅移动，不要快速闪烁
限制：
- 不要出现任何文字（不用 <text>），不要用 <image>、<script>、<style>、<foreignObject>、<use>、<a>、外部链接、滤镜
- 元素总数不超过 70 个（含动画元素），代码尽量精简"""


def _clean_url_refs(value: str) -> str | None:
    for ref in _URL.findall(value):
        if not ref.strip().strip("'\"").startswith("#"):
            return None
    return value


def sanitize_svg(text: str) -> str | None:
    """白名单清洗；结构不合法或清洗后为空返回 None。"""
    m = re.search(r"<svg[\s\S]*</svg>", text)
    if not m:
        return None
    try:
        root = ET.fromstring(m.group(0))
    except ET.ParseError:
        return None

    def local(tag: str) -> str:
        return tag.split("}", 1)[-1]

    def clean(el: ET.Element) -> None:
        for child in list(el):
            if local(child.tag) not in ALLOWED_TAGS:
                el.remove(child)
                continue
            clean(child)
        for k in list(el.attrib):
            name = local(k)
            v = el.attrib[k]
            if name not in ALLOWED_ATTRS or "javascript:" in v.lower() or "expression(" in v.lower():
                del el.attrib[k]
            elif "url(" in v and _clean_url_refs(v) is None:
                del el.attrib[k]
        # 动画只能改展示属性；目标属性不合规就整条动画删掉
        for child in list(el):
            if local(child.tag) in ANIM_TAGS and child.get("attributeName") not in ANIMATABLE:
                el.remove(child)
        el.text = None if local(el.tag) != "title" else el.text
        el.tail = None

    if local(root.tag) != "svg":
        return None
    clean(root)
    root.set("viewBox", root.get("viewBox") or "0 0 640 360")
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    if not any(local(c.tag) not in ANIM_TAGS for c in root):
        return None
    return ET.tostring(root, encoding="unicode")


def generate_cover(item_id: int, name: str, summary: str, category: str, fg: str, bg: str) -> str | None:
    """生成并保存 SVG 封面，返回 media 下的相对路径；失败返回 None（调用方保留占位图）。"""
    if not settings.ai_enabled:
        return None
    try:
        data = _chat_json(
            COVER_PROMPT.replace("{fg}", fg).replace("{bg}", bg),
            f"项目名称：{name}\n分类：{category}\n简介：{summary or '无'}",
            "AI-3",
        )
    except RuntimeError:
        return None
    svg = sanitize_svg(str(data.get("svg") or ""))
    if not svg:
        return None
    covers = settings.media_dir / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    fname = f"{item_id}-ai-{hashlib.sha1(svg.encode()).hexdigest()[:10]}.svg"
    (covers / fname).write_text(svg, encoding="utf-8")
    return f"covers/{fname}"


# v3.0 蓝白主题：各大类只在蓝色系里做深浅区分（与前端 categoryStyle.js 保持一致）
THEME = ("#1E56D6", "#EAF1FE")
GROUP_COLORS = {
    "coding": ("#1E56D6", "#EAF1FE"), "office": ("#2F6BF0", "#EAF1FE"), "writing": ("#2B6CB0", "#EAF1FE"),
    "image": ("#3A7BEA", "#EAF1FE"), "video": ("#1E56D6", "#EAF1FE"), "audio": ("#2F6BF0", "#EAF1FE"),
    "vision": ("#0B6E8C", "#EAF1FE"), "language": ("#3446B8", "#EAF1FE"), "agent": ("#1E56D6", "#EAF1FE"),
    "research": ("#2B6CB0", "#EAF1FE"), "infra": ("#3E516B", "#EAF1FE"), "ecosystem": ("#0B2F7A", "#EAF1FE"),
}
# 换主题时改这个标记：启动时发现旧主题画的 AI 封面会在后台全部重画一次
COVER_THEME = "v3-blue-motion"
