"""AI-1 / AI-2 / AI-6 合并为一次调用：从 README / SKILL.md 提炼描述、安装步骤并判定分类。
未配置 AI 或调用失败时，用规则兜底，保证本地无 Key 也能跑通。"""

import json
import re
import time
from dataclasses import dataclass, field

import httpx

from ..config import settings
from ..db import SessionLocal
from ..models import AiCall
from ..seed import FALLBACK_CODE, KINDS, SKILL_FALLBACK_CODE

MAX_DOC_CHARS = 12000


@dataclass
class SourceDoc:
    kind: str  # skill / repo
    name: str
    full_name: str
    clone_url: str
    sub_path: str
    gh_description: str
    topics: list[str]
    text: str  # SKILL.md（去掉 frontmatter）或 README
    frontmatter: dict = field(default_factory=dict)


@dataclass
class Extracted:
    summary: str
    description: str
    install_steps: list[dict]
    category_code: str
    confidence: float
    by_ai: bool
    error: str = ""  # AI 调用失败时记录原因，内容退回规则提炼
    kind: str = ""  # 使用类型，见 seed.KINDS
    kind_confidence: float | None = None
    search_tags: list = field(default_factory=list)


# ---------------- AI ----------------

SYSTEM_PROMPT = """你是一个开源资源整理助手。用户会给你一个 GitHub 仓库或其中一个 Agent Skill 的说明文档，
请用简体中文输出一个 JSON 对象，不要输出任何其他内容：
{
  "summary": "一句话说明它是干嘛的，不超过 40 个汉字",
  "description": "功能介绍，150~400 字，可分 2~4 段（段落之间用 \\n\\n），讲清楚能做什么、适合什么场景、有什么特点",
  "install_steps": [{"title": "步骤说明", "command": "要执行的命令，没有就填 null", "note": "补充说明，没有就填 null"}],
  "category_code": "从给定领域分类列表中选一个最贴切的 code（按它用在什么事上选）",
  "confidence": 0.0~1.0 之间的数字，表示分类判断的把握,
  "kind": "使用类型，从给定列表中选一个 key（按谁来用、怎么用选）",
  "kind_confidence": 0.0~1.0,
  "search_tags": ["10~20 个搜索标签：中英文同义词与常见说法、用途、场景、适合人群、技术领域，每个 1~6 个字或 1~3 个英文单词"]
}
要求：
- 所有文字字段（summary、description、install_steps 的 title 和 note）必须是简体中文。原文是英文时要翻译成通顺的中文，
  产品名、命令、包名、文件路径等专有名词保留原文。
- install_steps 按实际顺序给出 2~6 步，命令必须来自文档原文或是标准做法（如 git clone、pip install），不要编造不存在的包名。
- 如果是 Agent Skill，安装步骤应说明如何放到 Claude Code 的 skills 目录（~/.claude/skills/ 或项目 .claude/skills/），或通过插件市场安装（若文档有说明）。
- category_code 只能取列表里出现过的 code；kind 只能取使用类型列表里的 key。
- 领域分类和使用类型是两个独立的维度：例如一个做语音识别的 SKILL.md，领域是「语音识别」，使用类型是 agent_skill。"""


def kinds_prompt() -> str:
    return "\n".join(f"- {k}：{label}——{desc}" for k, (label, _, desc) in KINDS.items())


def _build_user_prompt(doc: SourceDoc, categories: list[tuple[str, str, str]]) -> str:
    cat_lines = "\n".join(f"- {code}：{name}（{remark}）" for code, name, remark in categories)
    meta = [
        f"类型：{'Agent Skill（仓库中的一个 SKILL.md 技能包）' if doc.kind == 'skill' else 'GitHub 仓库'}",
        f"名称：{doc.name}",
        f"仓库：{doc.full_name}" + (f"，子目录：{doc.sub_path}" if doc.sub_path else ""),
        f"克隆地址：{doc.clone_url}",
        f"仓库简介：{doc.gh_description or '无'}",
        f"Topics：{', '.join(doc.topics) or '无'}",
    ]
    if doc.frontmatter:
        meta.append(f"SKILL.md frontmatter：{json.dumps(doc.frontmatter, ensure_ascii=False)}")
    return (
        "\n".join(meta)
        + f"\n\n可选领域分类：\n{cat_lines}\n\n使用类型：\n{kinds_prompt()}\n\n文档内容：\n"
        + doc.text[:MAX_DOC_CHARS]
    )


def model_label(model: str | None = None) -> str:
    """模型 id → 界面上显示的名字（AI 标签）。"""
    model = model or settings.ai_text_model
    return settings.model_labels.get(model, model)


def _log_call(purpose: str, ok: bool, latency_ms: int, usage: dict | None, error: str = "") -> None:
    from . import billing

    uid = billing.owner()
    tin, tout = (usage or {}).get("prompt_tokens"), (usage or {}).get("completion_tokens")
    with SessionLocal() as db:
        db.add(AiCall(
            purpose=purpose, model=settings.ai_text_model, ok=ok, latency_ms=latency_ms, error=error[:2000],
            tokens_in=tin, tokens_out=tout, user_id=uid,
        ))
        db.commit()
    if ok and uid:
        billing.consume(uid, (tin or 0) + (tout or 0), purpose)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("no JSON object", text, 0)
    # raw_decode 只读第一个完整对象，容忍模型在后面多输出内容
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def _chat_json(system: str, user, purpose: str, attempts: int = 3, temperature: float = 0.2) -> dict:
    """调用 OpenAI 兼容接口并解析 JSON。网络抖动或模型偶尔输出不合法 JSON 时自动重试。"""
    url = settings.ai_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.ai_text_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.ai_api_key}"}
    last = ""
    for attempt in range(1, attempts + 1):
        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=180) as c:
                r = c.post(url, json=body, headers=headers)
                if r.status_code == 400 and "response_format" in r.text:
                    body.pop("response_format")
                    r = c.post(url, json=body, headers=headers)
                r.raise_for_status()
                data = r.json()
            result = _parse_json(data["choices"][0]["message"]["content"])
            _log_call(purpose, True, int((time.monotonic() - t0) * 1000), data.get("usage"))
            return result
        except (httpx.TransportError, json.JSONDecodeError) as e:
            last = str(e)
            _log_call(purpose, False, int((time.monotonic() - t0) * 1000), None, f"第 {attempt} 次：{last}")
            time.sleep(2 * attempt)
        except httpx.HTTPStatusError as e:
            last = e.response.text[:300]
            _log_call(purpose, False, int((time.monotonic() - t0) * 1000), None, last)
            if e.response.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(5 * attempt)
        except Exception as e:
            last = str(e)
            _log_call(purpose, False, int((time.monotonic() - t0) * 1000), None, last)
            break
    raise RuntimeError(f"AI 调用失败：{last}")


def _normalize_steps(raw) -> list[dict]:
    steps = []
    for s in raw or []:
        if isinstance(s, str):
            s = {"title": s}
        if not isinstance(s, dict) or not s.get("title"):
            continue
        steps.append({
            "title": str(s["title"]).strip(),
            "command": (str(s["command"]).strip() or None) if s.get("command") else None,
            "note": (str(s["note"]).strip() or None) if s.get("note") else None,
        })
    return steps


def extract(doc: SourceDoc, categories: list[tuple[str, str, str]]) -> Extracted:
    """categories: [(code, name, remark)]，仅启用的子类。"""
    valid = {c[0] for c in categories}
    fallback = extract_by_rules(doc, valid)
    if not settings.ai_enabled:
        return fallback

    try:
        data = _chat_json(SYSTEM_PROMPT, _build_user_prompt(doc, categories), "AI-1")
    except RuntimeError as e:
        fallback.error = str(e)
        return fallback

    code = data.get("category_code")
    steps = _normalize_steps(data.get("install_steps"))
    confidence = clamp01(data.get("confidence"))
    kind = data.get("kind") if data.get("kind") in KINDS else fallback.kind
    result = Extracted(
        summary=str(data.get("summary") or fallback.summary).strip()[:200],
        description=str(data.get("description") or fallback.description).strip(),
        install_steps=steps or fallback.install_steps,
        category_code=code if code in valid else fallback.category_code,
        confidence=confidence if code in valid else fallback.confidence,
        by_ai=True,
        kind=kind,
        kind_confidence=clamp01(data.get("kind_confidence")) if data.get("kind") in KINDS else fallback.kind_confidence,
        search_tags=list(dict.fromkeys(str(t).strip()[:30] for t in data.get("search_tags") or [] if str(t).strip()))[:20],
    )
    _ensure_chinese(result)
    return result


def clamp01(v, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


# ---------------- 中文化 ----------------

_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")


def is_mostly_english(text: str) -> bool:
    """英文字母多、汉字少，视为需要翻译。命令、短名称这类不在此判断。"""
    if not text:
        return False
    cjk, latin = len(_CJK.findall(text)), len(_LATIN.findall(text))
    return latin >= 12 and cjk < latin * 0.15


TRANSLATE_PROMPT = """你是技术文档翻译。把用户给出的 JSON 数组里每一段文字翻译成通顺的简体中文，
产品名、命令、包名、文件路径、代码保留原文；已经是中文的原样返回；保持段落换行。
只输出 JSON 对象：{"items": ["译文1", "译文2", ...]}，items 与输入一一对应、数量相同。"""


def translate_texts(texts: list[str]) -> list[str]:
    """批量译成中文。未配置 AI、无需翻译或失败时原样返回。"""
    todo = [i for i, t in enumerate(texts) if is_mostly_english(t)]
    if not settings.ai_enabled or not todo:
        return texts
    try:
        data = _chat_json(TRANSLATE_PROMPT, json.dumps([texts[i] for i in todo], ensure_ascii=False), "AI-7")
    except RuntimeError:
        return texts
    items = data.get("items")
    if not isinstance(items, list) or len(items) != len(todo):
        return texts
    out = list(texts)
    for i, t in zip(todo, items):
        if isinstance(t, str) and t.strip():
            out[i] = t.strip()
    return out


def _ensure_chinese(r: Extracted) -> None:
    """模型偶尔不听话直接输出英文，这里兜一次翻译。"""
    fields = [r.summary, r.description]
    for s in r.install_steps:
        fields += [s["title"], s.get("note") or ""]
    if not any(is_mostly_english(f) for f in fields):
        return
    out = translate_texts(fields)
    r.summary, r.description = out[0], out[1]
    for i, s in enumerate(r.install_steps):
        s["title"] = out[2 + i * 2]
        if s.get("note"):
            s["note"] = out[3 + i * 2]


# ---------------- 规则兜底 ----------------

def _clean_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text


def _paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", _clean_markdown(text)):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines or all(ln.startswith(("#", "|", "-", "*", ">", "=")) and len(ln) < 4 for ln in lines):
            continue
        if lines[0].startswith("#") or lines[0].startswith("|"):
            continue
        para = " ".join(ln.lstrip("> ") for ln in lines)
        if len(para) >= 20:
            out.append(para)
    return out


_INSTALL_HEAD = re.compile(r"^#{1,4}\s*.*(install|安装|quick\s*start|getting\s*started|快速开始|setup|部署|usage|使用)", re.I)


def _install_from_readme(text: str) -> list[dict]:
    steps = []
    sections = re.split(r"(?m)^(?=#{1,4}\s)", text)
    for sec in sections:
        head = sec.splitlines()[0] if sec else ""
        if not _INSTALL_HEAD.match(head):
            continue
        title = head.lstrip("#").strip()
        for code in re.findall(r"```[\w-]*\n(.*?)```", sec, re.S):
            code = code.strip()
            if code and len(code) < 600:
                steps.append({"title": title, "command": code, "note": None})
            if len(steps) >= 5:
                return steps
    return steps


def _default_steps(doc: SourceDoc) -> list[dict]:
    repo_dir = doc.full_name.split("/")[-1]
    if doc.kind == "skill":
        src = f"{repo_dir}/{doc.sub_path}" if doc.sub_path else repo_dir
        target = doc.sub_path.rsplit("/", 1)[-1] if doc.sub_path else repo_dir
        return [
            {"title": "克隆仓库", "command": f"git clone {doc.clone_url}", "note": None},
            {"title": "复制 Skill 到 Claude Code 的 skills 目录（全局）", "command": f"cp -r {src} ~/.claude/skills/{target}",
             "note": "只想在某个项目里用，就复制到项目的 .claude/skills/ 目录"},
            {"title": "重启 Claude Code", "command": None, "note": "Skill 会按 SKILL.md 中的描述自动触发"},
        ]
    return [{"title": "克隆仓库", "command": f"git clone {doc.clone_url}", "note": "具体安装方式请参考仓库 README"}]


# 规则兜底只在 AI 不可用时使用，粗分即可，界面上标注为「规则兜底」
# (关键词, 分类) —— 按顺序匹配，先命中先用
_REPO_RULES = [
    (("model-context-protocol", "model context protocol", "mcp-server", "mcp"), "agent-connector"),
    (("speech-recognition", "asr", "whisper", "speech-to-text", "funasr", "sensevoice"), "model-asr"),
    (("voice-clone", "voice-cloning", "voice-conversion", "rvc"), "model-voice-clone"),
    (("text-to-speech", "tts", "speech-synthesis", "cosyvoice"), "model-tts"),
    (("music-generation", "music"), "model-music"),
    (("text-to-video", "video-generation", "image-to-video"), "model-text2video"),
    (("digital-human", "talking-head", "lip-sync"), "model-digital-human"),
    (("text-to-image", "stable-diffusion", "diffusion", "flux", "image-generation"), "model-text2image"),
    (("image-editing", "super-resolution", "inpainting", "background-removal"), "model-image-edit"),
    (("text-to-3d", "image-to-3d", "3d-generation"), "model-3d"),
    (("ocr", "document-parsing", "pdf-parser"), "model-ocr"),
    (("object-detection", "segmentation", "yolo"), "model-detection"),
    (("face-recognition", "face-swap", "deepfake"), "model-face"),
    (("vision-language", "vlm", "multimodal"), "model-vlm"),
    (("embedding", "reranker", "rerank"), "model-embedding"),
    (("code-llm", "code-generation", "coder"), "model-llm-code"),
    (("reasoning",), "model-llm-reasoning"),
    (("awesome", "awesome-list"), "dev-awesome"),
    (("rag", "retrieval-augmented-generation", "knowledge-base"), "agent-rag"),
    (("browser-agent", "browser-use", "computer-use"), "agent-browser"),
    (("coding-agent", "ai-coding"), "coding-assistant"),
    (("workflow", "workflow-automation", "low-code"), "agent-workflow"),
    (("agent", "agents", "multi-agent", "ai-agent"), "agent-framework"),
    (("inference", "serving", "llm-inference", "llama-cpp", "ollama"), "dev-inference"),
    (("fine-tuning", "finetuning", "lora", "rlhf", "training"), "dev-finetune"),
    (("dataset", "datasets"), "dev-dataset"),
    (("benchmark", "evaluation", "eval"), "dev-eval"),
    (("vscode-extension", "jetbrains-plugin", "neovim", "cli", "command-line"), "coding-toolchain"),
    (("llm", "large-language-model", "language-model", "chatgpt"), "model-llm-general"),
    (("sdk", "framework", "library"), "agent-framework"),
]

_SKILL_RULES = [
    (("skill-creator", "create skill", "skill development", "write skills", "testing skills"), "skill-meta"),
    (("docx", "pptx", "xlsx", "pdf", "word document", "powerpoint", "excel", "spreadsheet", "slides"), "office-docs"),
    (("design", "figma", "canvas", "poster", "brand", "ui ", "frontend design", "art", "theme"), "design-ui"),
    (("data analysis", "sql", "chart", "dashboard", "csv", "analytics"), "data-analysis"),
    (("browser", "playwright", "puppeteer", "automation", "scrape", "web testing"), "agent-browser"),
    (("research", "search", "literature", "paper"), "data-research"),
    (("write", "writing", "blog", "copy", "content", "translate", "communication"), "writing-copy"),
    (("review", "test", "debug"), "coding-review"),
]

_DEV_CODES = {"dev-awesome", "dev-inference", "dev-finetune", "dev-dataset", "dev-eval", "agent-framework"}


def _kind_by_rules(doc: SourceDoc, code: str) -> str:
    if doc.kind == "skill" or code == "agent-connector":
        return "agent_skill"
    if code.startswith("model-"):
        return "model"
    if code in _DEV_CODES:
        return "dev"
    return ""


def _match_rules(rules, haystack: str, tokens: set[str], valid: set[str]) -> str | None:
    for words, code in rules:
        if code not in valid:
            continue
        for w in words:
            if w in tokens or re.search(rf"(?<![a-z0-9]){re.escape(w.strip())}(?![a-z0-9])", haystack):
                return code
    return None


def extract_by_rules(doc: SourceDoc, valid: set[str]) -> Extracted:
    paras = _paragraphs(doc.text)
    fm_desc = doc.frontmatter.get("description", "")
    summary = (fm_desc or doc.gh_description or (paras[0] if paras else "") or doc.name).strip()
    if len(summary) > 120:
        summary = summary[:118] + "…"
    description = "\n\n".join(([fm_desc] if fm_desc else []) + paras[:3]) or doc.gh_description

    steps = [] if doc.kind == "skill" else _install_from_readme(doc.text)
    steps = steps or _default_steps(doc)

    tokens = {t.lower() for t in doc.topics}
    haystack = " ".join([doc.name, doc.sub_path, doc.gh_description, fm_desc, " ".join(doc.topics)]).lower()
    if doc.kind == "skill":
        code = _match_rules(_SKILL_RULES, haystack, tokens, valid) or SKILL_FALLBACK_CODE
    else:
        code = _match_rules(_REPO_RULES, haystack, tokens, valid) or FALLBACK_CODE
    if code not in valid:
        code = next(iter(valid)) if valid else FALLBACK_CODE

    return Extracted(summary, description, steps, code, 0.3, False, kind=_kind_by_rules(doc, code), kind_confidence=0.3)


# ---------------- 收录预判（自动采集里“疑似相关”的仓库） ----------------

PREJUDGE_PROMPT = """你在为一个“Agent Skill / AI 模型 / AI 工具”资源站筛选 GitHub 仓库。
根据仓库名称、简介和 topics 判断它是否值得收录：Agent Skill、开源 AI 模型、MCP Server、AI 智能体框架、
AI 开发与部署工具属于收录范围；普通业务项目、教程合集以外的无关仓库不收录。
只输出 JSON：{"relevant": true 或 false, "reason": "一句中文理由，不超过 40 字"}"""


def prejudge(name: str, description: str, topics: list[str]) -> tuple[bool | None, str]:
    """返回 (是否相关, 理由)。未配置 AI 或调用失败时返回 (None, "")，交给人工确认。"""
    if not settings.ai_enabled:
        return None, ""
    try:
        data = _chat_json(PREJUDGE_PROMPT, f"名称：{name}\n简介：{description or '无'}\nTopics：{', '.join(topics) or '无'}", "AI-6")
    except RuntimeError:
        return None, ""
    relevant = data.get("relevant")
    return (relevant if isinstance(relevant, bool) else None), str(data.get("reason") or "")[:200]
