"""需要「判断」的地方统一交给大模型：收录筛选、合集判断、分类、搜索意图、相关度、长文抽取、仓库挑选、榜单详解、收藏整理。

每个函数在 AI 不可用或调用失败时抛 JudgeUnavailable，由调用方决定兜底方式（规则、交给人工或提示用户）。
能合并的判断尽量一次调用处理一批，控制 token 消耗。
"""

import json
import re

from ..config import settings
from ..seed import KINDS
from .extract import _chat_json, clamp01, kinds_prompt


class JudgeUnavailable(Exception):
    pass


def _ask(system: str, user: str, purpose: str, temperature: float = 0.2) -> dict:
    if not settings.ai_enabled:
        raise JudgeUnavailable("未配置 AI 接口")
    try:
        return _chat_json(system, user, purpose, temperature=temperature)
    except RuntimeError as e:
        raise JudgeUnavailable(str(e)) from e


def _kind(v) -> str:
    return v if v in KINDS else ""


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- 自动采集：收录筛选

SCREEN_PROMPT = """你在为「Skill Pocket」筛选 GitHub 仓库。这个站收录：Agent Skill、MCP Server 等给 AI Agent 用的能力，
开源 AI 模型，AI 工具应用，AI 开发资源（框架、推理部署、训练、数据集、评测、精选清单），有参考价值的 AI 项目 Demo。
不收录：与 AI 无关的普通项目、个人练习仓库、纯营销页面、空仓库。

用户会给你一批仓库（名称、简介、topics、语言、星标）。逐个判断，只输出 JSON：
{"results": [{"full_name": "...", "relevant": true/false, "confidence": 0.0~1.0, "kind": "使用类型 key", "reason": "一句中文理由，不超过 40 字"}]}
results 与输入一一对应、顺序相同。信息不足、拿不准时 relevant 仍给出倾向，但 confidence 要低。

使用类型：
"""


def screen_repos(repos: list[dict]) -> list[dict]:
    """repos: [{full_name, description, topics, language, stars}] → [{relevant, confidence, kind, reason}]"""
    brief = [{"full_name": r["full_name"], "description": (r.get("description") or "")[:300],
              "topics": (r.get("topics") or [])[:12], "language": r.get("language") or "", "stars": r.get("stars")}
             for r in repos]
    data = _ask(SCREEN_PROMPT + kinds_prompt(), _dump(brief), "AI-6")
    by_name = {str(x.get("full_name", "")).lower(): x for x in data.get("results") or [] if isinstance(x, dict)}
    out = []
    for i, r in enumerate(repos):
        x = by_name.get(r["full_name"].lower())
        if x is None and i < len(data.get("results") or []):
            x = data["results"][i] if isinstance(data["results"][i], dict) else None
        if x is None or not isinstance(x.get("relevant"), bool):
            out.append({"relevant": None, "confidence": 0.0, "kind": "", "reason": "AI 未给出判断"})
            continue
        out.append({"relevant": x["relevant"], "confidence": clamp01(x.get("confidence")), "kind": _kind(x.get("kind")),
                    "reason": str(x.get("reason") or "")[:200]})
    return out


COLLECTION_PROMPT = """一个 GitHub 仓库里有很多 SKILL.md（Agent Skill）。判断它属于哪种情况，只输出 JSON：
{"mode": "split" 或 "whole", "reason": "一句中文理由"}
- split：作者自己维护的一组 Skill（同一个产品 / 团队出品，每个 Skill 都值得单独展示），应拆成多个条目
- whole：搬运、汇总、收集别人 Skill 的合集，或数量多到逐个展示没有意义，应整体收录为一个条目"""


def judge_collection(full_name: str, description: str, skill_dirs: list[str]) -> tuple[str, str]:
    user = f"仓库：{full_name}\n简介：{description or '无'}\nSkill 数量：{len(skill_dirs)}\nSkill 目录（前 80 个）：\n" + \
        "\n".join(skill_dirs[:80])
    data = _ask(COLLECTION_PROMPT, user, "AI-6")
    mode = data.get("mode") if data.get("mode") in ("split", "whole") else "whole"
    return mode, str(data.get("reason") or "")[:200]


# ---------------------------------------------------------------- 存量重分类

CLASSIFY_PROMPT = """给一批已收录的条目重新判定两个维度，只输出 JSON：
{"results": [{"id": 条目 id, "category_code": "领域分类 code", "confidence": 0.0~1.0, "kind": "使用类型 key", "kind_confidence": 0.0~1.0}]}
- 领域分类：按它用在什么事上选，只能取列表里的 code
- 使用类型：按谁来用、怎么用选，只能取列表里的 key
- 两个维度独立判断，例如做语音识别的 SKILL.md：领域「语音识别」，使用类型 agent_skill"""


def classify_items(items: list[dict], categories: list[tuple[str, str, str]]) -> dict[int, dict]:
    """items: [{id, name, repo, type, summary, description, topics}] → {id: {category_code, confidence, kind, kind_confidence}}"""
    valid = {c[0] for c in categories}
    cats = "\n".join(f"- {code}：{name}（{remark}）" for code, name, remark in categories)
    user = f"领域分类：\n{cats}\n\n使用类型：\n{kinds_prompt()}\n\n条目：\n{_dump(items)}"
    data = _ask(CLASSIFY_PROMPT, user, "AI-2")
    out = {}
    for x in data.get("results") or []:
        if not isinstance(x, dict):
            continue
        try:
            iid = int(x.get("id"))
        except (TypeError, ValueError):
            continue
        out[iid] = {
            "category_code": x.get("category_code") if x.get("category_code") in valid else None,
            "confidence": clamp01(x.get("confidence")),
            "kind": _kind(x.get("kind")),
            "kind_confidence": clamp01(x.get("kind_confidence")),
        }
    return out


# ---------------------------------------------------------------- 搜索添加

PLAN_PROMPT = """用户想在 GitHub 上找 Agent Skill、AI 模型、AI 工具或项目。理解用户的中文（或英文）需求，生成搜索方案，只输出 JSON：
{
  "intent": "named（在找某个具体项目 / Skill）、feature（按功能需求找）或 list（输入里列了好几个不同的项目名，或是一段介绍多个项目的文字，应该逐个识别而不是当成一次搜索）",
  "kind": "最可能的使用类型 key，判断不了填空字符串",
  "understanding": "用一句中文复述你理解的需求",
  "queries": ["3~5 条 GitHub 仓库搜索语句"],
  "skill_queries": ["如果可能是 Agent Skill，给 1~3 个可能的 Skill 名称或英文关键词，否则为空数组"]
}
写 queries 的要求：
- 用英文，2~4 个关键词，覆盖不同说法（同义词、领域术语、常见项目命名方式），不要逐字翻译
- 可以用 GitHub 搜索限定符，如 topic:xxx、language:python、stars:>50，但每条最多一个限定符
- named 意图时第一条直接用项目名（加 in:name）
- 不要和「已经用过的搜索语句」重复"""


def plan_search(q: str, avoid: list[str] | None = None) -> dict:
    user = f"需求：{q}\n\n使用类型：\n{kinds_prompt()}"
    if avoid:
        user += "\n\n已经用过的搜索语句（换别的说法）：\n" + "\n".join(avoid)
    data = _ask(PLAN_PROMPT, user, "AI-8", temperature=0.5 if avoid else 0.2)
    queries = [str(x).strip()[:120] for x in data.get("queries") or [] if str(x).strip()]
    queries = [x for x in queries if x not in (avoid or [])][:5]
    if not queries:
        raise JudgeUnavailable("AI 没有给出搜索语句")
    return {
        "intent": data.get("intent") if data.get("intent") in ("named", "feature", "list") else "feature",
        "kind": _kind(data.get("kind")),
        "understanding": str(data.get("understanding") or "")[:200],
        "queries": queries,
        "skill_queries": [str(x).strip()[:60] for x in data.get("skill_queries") or [] if str(x).strip()][:3],
    }


RERANK_PROMPT = """根据用户需求，给 GitHub 搜索到的候选打分并排序，只输出 JSON：
{"results": [{"full_name": "...", "score": 0~100, "kind": "使用类型 key", "reason": "一句中文说明它是什么、为什么符合（或不符合）需求，不超过 50 字", "desc_zh": "把它的英文简介忠实译成通顺的中文，不超过 80 字；简介为空时根据名称和 topics 概括它是什么"}]}
- score 表示和需求的相关度：90+ 正是要找的；60~89 相关可用；40~59 沾边；40 以下基本无关
- 只看是否满足需求，不要因为星标高就给高分；用户点名的项目给最高分
- 每个候选都要给出结果"""


def rerank(need: str, candidates: list[dict]) -> dict[str, dict]:
    """candidates: [{full_name, description, topics, stars, language}] → {full_name 小写: {score, kind, reason}}"""
    brief = [{"full_name": c["full_name"], "description": (c.get("description") or "")[:240],
              "topics": (c.get("topics") or [])[:8], "stars": c.get("stars"), "language": c.get("language") or ""}
             for c in candidates]
    data = _ask(RERANK_PROMPT, f"需求：{need}\n\n使用类型：\n{kinds_prompt()}\n\n候选：\n{_dump(brief)}", "AI-8")
    out = {}
    for x in data.get("results") or []:
        if isinstance(x, dict) and x.get("full_name"):
            try:
                score = max(0, min(100, int(x.get("score", 0))))
            except (TypeError, ValueError):
                score = 0
            out[str(x["full_name"]).lower()] = {"score": score, "kind": _kind(x.get("kind")),
                                                "reason": str(x.get("reason") or "")[:200],
                                                "desc_zh": str(x.get("desc_zh") or "")[:200]}
    return out


# ---------------------------------------------------------------- 长文识别

MENTIONS_PROMPT = """下面是一篇文章的一部分（可能是博主推荐清单、评测、教程）。找出其中提到的所有 Agent Skill、AI 模型、
MCP Server、AI 工具应用、开源项目或 GitHub 仓库，只输出 JSON：
{"items": [{
  "name": "名称（照原文）",
  "repo": "owner/repo，原文里有链接或你确定知道就填，否则 null",
  "kind": "使用类型 key，判断不了填空字符串",
  "open_source": true / false / null（明确是闭源商业产品填 false）,
  "homepage": "官网链接，原文里有就填，否则 null",
  "context": "原文中提到它的那一句话（原样摘录，不超过 120 字）",
  "description": "一句中文说明它是什么"
}]}
要求：
- 只列原文真实提到的，不要补充；同一个只列一次
- 作者本人、公司名、平台名（如 GitHub、微信）、编程语言、通用概念不算
- 文章被截断时只处理看到的部分"""


def extract_mentions(chunk: str) -> list[dict]:
    data = _ask(MENTIONS_PROMPT + "\n\n使用类型：\n" + kinds_prompt(), chunk, "AI-9")
    out = []
    for x in data.get("items") or []:
        if not isinstance(x, dict) or not str(x.get("name") or "").strip():
            continue
        repo = x.get("repo")
        repo = repo.strip().strip("/") if isinstance(repo, str) else None
        repo = repo if repo and re.fullmatch(r"[\w.-]+/[\w.-]+", repo) else None
        out.append({
            "name": str(x["name"]).strip()[:200],
            "repo": repo,
            "kind": _kind(x.get("kind")),
            "open_source": x.get("open_source") if isinstance(x.get("open_source"), bool) else None,
            "homepage": str(x.get("homepage") or "").strip()[:500] or None,
            "context": str(x.get("context") or "").strip()[:240],
            "description": str(x.get("description") or "").strip()[:240],
        })
    return out


PICK_PROMPT = """文章或截图里提到了一个项目，系统在 GitHub 上搜到了几个候选仓库。结合名称和原文上下文，判断哪个才是它，只输出 JSON：
{"full_name": "选中的 owner/repo，都不是就填 null", "confidence": 0.0~1.0, "reason": "一句中文理由"}
注意：同名仓库常有搬运、fork、同名不同物，优先选官方 / 原作者 / 星标与描述都吻合的那个。"""


def pick_repo(name: str, context: str, candidates: list[dict]) -> tuple[str | None, float, str]:
    brief = [{"full_name": c["full_name"], "description": (c.get("description") or "")[:200], "stars": c.get("stars")}
             for c in candidates]
    data = _ask(PICK_PROMPT, f"名称：{name}\n上下文：{context or '无'}\n候选：\n{_dump(brief)}", "AI-9")
    fn = data.get("full_name")
    names = {c["full_name"].lower(): c["full_name"] for c in candidates}
    fn = names.get(str(fn).lower()) if fn else None
    return fn, clamp01(data.get("confidence"), 0.0), str(data.get("reason") or "")[:200]


# ---------------------------------------------------------------- 榜单中文详解

BLURB_PROMPT = """为排行榜写一段中文详解，让人一眼看懂这个项目。只输出 JSON：{"blurb": "..."}
要求：2~3 句，总共 60~120 个汉字；依次说清它是什么、能做什么、适合谁或亮点；
不要复述星标数据，不要空话套话；产品名、命令等专有名词保留原文。"""


def write_blurb(name: str, full_name: str, summary: str, description: str, doc_head: str) -> str:
    user = f"名称：{name}\n仓库：{full_name}\n已有简介：{summary}\n已有介绍：{description[:800]}\n\n文档开头：\n{doc_head[:3000]}"
    data = _ask(BLURB_PROMPT, user, "AI-10")
    blurb = str(data.get("blurb") or "").strip()
    if not blurb:
        raise JudgeUnavailable("AI 没有给出详解")
    return blurb[:400]


# ---------------------------------------------------------------- 收藏整理建议

ORGANIZE_PROMPT = """用户在整理收藏。给出每个未整理条目建议放进哪些已有分类，只输出 JSON：
{"results": [{"item_id": 条目 id, "folder_ids": [已有分类 id，可多个，可为空], "new_folder": "已有分类都不合适时建议新建的分类名（不超过 10 个字），否则 null"}]}
- 按分类名的含义理解用户的整理习惯，只在确实匹配时才放
- 尽量用已有分类，new_folder 少用；多个条目建议的新分类名要一致"""


def suggest_folders(dimension: str, folders: list[dict], items: list[dict]) -> list[dict]:
    valid = {f["id"] for f in folders}
    user = f"维度：{dimension}\n已有分类：{_dump(folders)}\n\n未整理条目：{_dump(items)}"
    data = _ask(ORGANIZE_PROMPT, user, "AI-11")
    item_ids = {i["id"] for i in items}
    out = []
    for x in data.get("results") or []:
        if not isinstance(x, dict):
            continue
        try:
            iid = int(x.get("item_id"))
        except (TypeError, ValueError):
            continue
        if iid not in item_ids:
            continue
        fids = [f for f in (x.get("folder_ids") or []) if isinstance(f, int) and f in valid]
        new = str(x.get("new_folder") or "").strip()[:20] or None
        if fids or new:
            out.append({"item_id": iid, "folder_ids": fids, "new_folder": new})
    return out


# ---------------------------------------------------------------- 昵称审核

NICKNAME_PROMPT = """判断一个网站用户昵称是否适合公开展示。不合适的情况：辱骂、色情、暴力、政治敏感、冒充官方（如「管理员」「客服」「官方」）、
广告引流（含网址、微信号、QQ 号、手机号）。普通昵称、网名、英文名、谐音梗都可以。只输出 JSON：{"ok": true/false, "reason": "不合适时用一句中文说明原因"}"""


def check_nickname(name: str) -> tuple[bool, str]:
    data = _ask(NICKNAME_PROMPT, name, "AI-12")
    ok = data.get("ok")
    return (ok if isinstance(ok, bool) else True), str(data.get("reason") or "")[:100]


# ---------------------------------------------------------------- 用户提交审核

REVIEW_PROMPT = """你是「Skill Pocket」的内容审核员，审核用户提交的条目是否可以公开上线。只输出 JSON：
{"decision": "approve / reject / unsure", "confidence": 0.0~1.0, "reason": "一句中文理由，不超过 60 字", "checks": {"in_scope": true/false, "safe": true/false, "duplicate_of": 重复条目的 id 或 null, "quality_ok": true/false}}
审核标准：
1. 收录范围：Agent Skill、MCP Server、开源 AI 模型、AI 工具应用、AI 开发资源（框架、推理部署、训练、数据集、评测、精选清单）、有参考价值的 AI 项目 Demo；与 AI 无关的项目不收
2. 安全合规：违法、色情、赌博、恶意软件 / 病毒 / 木马、钓鱼、破解盗版、广告引流一律驳回
3. 重复：与「库中可能重复的条目」实际是同一个东西（同一仓库同一目录，或明显是同一产品的搬运副本）时驳回，并给出 duplicate_of
4. 质量：空仓库、几乎没有说明、明显是测试 / 占位内容时驳回
{strict}"""

STRICT_MAX = "你拥有最终决定权：必须在 approve 和 reject 中二选一，不能输出 unsure。"
STRICT_NORMAL = "信息不足以判断、或介于可收可不收之间时输出 unsure，交给管理员决定。"


def review_item(info: dict, similar: list[dict], must_decide: bool) -> dict:
    """info: {name, repo, kind, category, summary, description, stars, topics, submitter_note}"""
    prompt = REVIEW_PROMPT.replace("{strict}", STRICT_MAX if must_decide else STRICT_NORMAL)
    user = f"待审核条目：{_dump(info)}\n\n库中可能重复的条目：{_dump(similar) if similar else '无'}"
    data = _ask(prompt, user, "AI-13")
    decision = data.get("decision") if data.get("decision") in ("approve", "reject", "unsure") else "unsure"
    if must_decide and decision == "unsure":
        decision = "approve" if clamp01(data.get("confidence")) >= 0.5 else "reject"
    dup = (data.get("checks") or {}).get("duplicate_of")
    return {"decision": decision, "confidence": clamp01(data.get("confidence"), 0.5),
            "reason": str(data.get("reason") or "")[:200], "duplicate_of": dup if isinstance(dup, int) else None}


# ---------------------------------------------------------------- 搜索标签

TAGS_PROMPT = """给一批条目生成搜索标签，帮助用户用各种说法搜到它们。只输出 JSON：
{"results": [{"id": 条目 id, "tags": ["10~20 个标签"]}]}
标签要求：中英文都要有；覆盖同义词与常见说法（如 H5 / 移动端网页 / landing page）、用途、使用场景、适合人群、所属技术领域；
每个标签 1~6 个字或 1~3 个英文单词；不要重复条目名本身；不要空泛的词（如「工具」「好用」）。"""


def tags_for_items(items: list[dict]) -> dict[int, list[str]]:
    data = _ask(TAGS_PROMPT, _dump(items), "AI-14")
    out = {}
    for x in data.get("results") or []:
        try:
            iid = int(x.get("id"))
        except (TypeError, ValueError):
            continue
        tags = [str(t).strip()[:30] for t in x.get("tags") or [] if str(t).strip()]
        out[iid] = list(dict.fromkeys(tags))[:20]
    return out


# ---------------------------------------------------------------- 语义搜索：理解需求 + 精排

REFINE_PROMPT = """用户在一个收录 Agent Skill、AI 模型、AI 工具的网站里搜索，系统已经用向量检索找出了候选条目。
先用一句中文说明你理解的需求，再给每个候选按相关度打分。只输出 JSON：
{"understanding": "你理解的需求（如：找用于移动端 H5 页面设计的 Agent 技能），不超过 40 字",
 "results": [{"id": 条目 id, "score": 0~100, "reason": "为什么相关，不超过 20 字"}]}
- 90+：正是要找的；60~89：相关可用；40~59：沾边；40 以下：不相关
- 用户点名的项目给最高分；只看是否满足需求，不要因为星标高就给高分
- 每个候选都要给出结果"""


def refine_search(q: str, items: list[dict]) -> dict:
    """一次调用完成「理解需求 + 精排」（v2.2 起替代 understand_query + rank_search 两次调用）。"""
    data = _ask(REFINE_PROMPT, f"搜索：{q}\n\n候选：{_dump(items)}", "AI-15")
    out = {}
    for x in data.get("results") or []:
        try:
            iid, score = int(x.get("id")), max(0, min(100, int(x.get("score", 0))))
        except (TypeError, ValueError):
            continue
        out[iid] = {"score": score, "reason": str(x.get("reason") or "")[:60]}
    return {"understanding": str(data.get("understanding") or "")[:120], "results": out}


# ---------------------------------------------------------------- 对比（v2.3）

COMPARE_DIMENSIONS = ["定位与类型", "核心能力", "适用场景", "上手难度", "运行环境与依赖", "质量与活跃度", "成本", "许可证", "局限与风险"]

COMPARE_PROMPT = """你是「Skill Pocket」的选型顾问，帮用户在几个 AI Skill / 模型 / 工具之间做选择。
用户会给你 2~6 个条目，每个用代号（A、B、C…）标识，包含：名称、来源（本站收录 / GitHub）、仓库、使用类型、简介、
README 摘要、安装方式、星标、近 30 天星标增长、最近更新时间、是否归档、许可证。

按下面的步骤分析。只依据给出的资料，资料里没有的写「资料未提及」，不要编造：

1. 分组：判断哪些条目解决的是同一类问题（可以互相替代），哪些不是。
   同一类的放进同一组（type=same，至少 2 个）；和其他都不同类的单独成组（type=different），说明它是做什么的。
2. 对每个同类组逐个维度比较：{dims}。
   每个维度给出组内每个条目的简短描述（不超过 40 字），并标出这个维度上更好的一个代号（没有明显差别写 "equal"）。
3. 使用方法：每个条目给出 2~4 步上手方法（可以引用安装方式），每步不超过 40 字。
4. 推荐：按 2~3 个常见使用场景分别推荐一个条目并说明理由；
   如果有已归档、长期不更新（超过 1 年）或有安全风险的，在 warnings 里明确提醒。
5. 不同类的条目不要比较优劣，只说明「类型不同、作用不同」以及各自适合什么时候用。

只输出 JSON（代号用 A、B、C…）：
{{
  "summary": "一句话结论，不超过 60 字",
  "groups": [
    {{"type": "same" 或 "different", "title": "这一组解决什么问题（不超过 20 字）", "ids": ["A", "B"],
      "dimensions": [{{"name": "维度名", "values": {{"A": "描述", "B": "描述"}}, "better": "A 或 equal"}}],
      "note": "type=different 时说明它的作用、适合什么时候用；type=same 时可为空"}}
  ],
  "usage": {{"A": ["步骤1", "步骤2"]}},
  "recommendations": [{{"scenario": "场景（不超过 20 字）", "id": "A", "reason": "理由，不超过 60 字"}}],
  "warnings": [{{"id": "A", "text": "风险提醒，不超过 60 字"}}]
}}"""


def compare_items(subjects: list[dict]) -> dict:
    """subjects: [{code: "A", ...资料}] → 校验过的对比结果（代号原样保留，由调用方映射回条目）。"""
    codes = [s["code"] for s in subjects]
    data = _ask(COMPARE_PROMPT.format(dims="、".join(COMPARE_DIMENSIONS)), _dump(subjects), "AI-17", temperature=0.3)
    valid = set(codes)

    def ids(v) -> list[str]:
        return [x for x in (v or []) if isinstance(x, str) and x in valid]

    groups = []
    for g in data.get("groups") or []:
        if not isinstance(g, dict) or not ids(g.get("ids")):
            continue
        gid = list(dict.fromkeys(ids(g.get("ids"))))
        typ = "same" if g.get("type") == "same" and len(gid) >= 2 else "different"
        dims = []
        for d in g.get("dimensions") or [] if typ == "same" else []:
            if not isinstance(d, dict) or not isinstance(d.get("values"), dict):
                continue
            better = d.get("better") if d.get("better") in gid else "equal"
            dims.append({"name": str(d.get("name") or "")[:20],
                         "values": {k: str(v)[:120] for k, v in d["values"].items() if k in gid},
                         "better": better})
        groups.append({"type": typ, "title": str(g.get("title") or "")[:40], "ids": gid, "dimensions": dims,
                       "note": str(g.get("note") or "")[:300]})
    # AI 漏掉的条目单独成组，保证每个都出现
    seen = {i for g in groups for i in g["ids"]}
    for c in codes:
        if c not in seen:
            groups.append({"type": "different", "title": "", "ids": [c], "dimensions": [], "note": ""})
    usage = {k: [str(x)[:120] for x in v][:5] for k, v in (data.get("usage") or {}).items() if k in valid and isinstance(v, list)}
    recs = [{"scenario": str(r.get("scenario") or "")[:40], "id": r["id"], "reason": str(r.get("reason") or "")[:160]}
            for r in data.get("recommendations") or [] if isinstance(r, dict) and r.get("id") in valid][:4]
    warns = [{"id": w["id"], "text": str(w.get("text") or "")[:160]}
             for w in data.get("warnings") or [] if isinstance(w, dict) and w.get("id") in valid][:6]
    return {"summary": str(data.get("summary") or "")[:120], "groups": groups, "usage": usage,
            "recommendations": recs, "warnings": warns}


# ---------------------------------------------------------------- 用户反馈分析

FEEDBACK_PROMPT = """你是「Skill Pocket」（收录 Agent Skill / AI 模型 / AI 工具的网站，Vue 前端 + FastAPI 后端，
功能有：搜索、榜单、详情、收藏与收藏分类、评论与语音输入、新增 Skill（GitHub 链接 / 截图识别 / 长文识别 / 搜索添加）、
邮箱验证码登录、AI 提炼与审核、每日自动采集）的值班工程师。分析一条用户反馈，只输出 JSON：
{
  "suggested_category": "bug / feature / ux / content / account / other（用户选错类别时给出正确的）",
  "priority": "P0~P4（只有 bug 和 account 需要，其他填空字符串）",
  "priority_reason": "判定优先级的理由",
  "cause": "可能原因（结合描述、页面、诊断信息、服务端日志推断，说清楚是推测）",
  "modules": ["涉及的模块，如 登录 / 收藏 / 截图识别 / 搜索 / 前端样式"],
  "impact": "影响面：全部用户 / 部分用户 / 个别情况，并简述",
  "steps": ["建议的排查或修复步骤，2~5 条"],
  "summary": "一句话概括这条反馈（不超过 30 字）",
  "similar_ids": [与已有反馈实际是同一问题的 id]
}
优先级定义：
P0 全站不可用、数据丢失或泄露、安全问题；P1 核心功能（登录、收藏、新增 Skill、搜索）不可用且没有替代办法；
P2 功能异常但有绕过办法，或只影响部分用户；P3 界面、文案、样式等体验问题；P4 轻微问题或优化建议。"""


def analyze_feedback(fb: dict, server_logs: list[dict], recent: list[dict]) -> dict:
    user = f"反馈：{_dump(fb)}\n\n该用户近期的服务端日志：{_dump(server_logs) if server_logs else '无'}\n\n近期其他反馈：{_dump(recent) if recent else '无'}"
    data = _ask(FEEDBACK_PROMPT, user, "AI-16")
    cat = data.get("suggested_category") if data.get("suggested_category") in ("bug", "feature", "ux", "content", "account", "other") else ""
    pr = data.get("priority") if data.get("priority") in ("P0", "P1", "P2", "P3", "P4") else ""
    return {
        "suggested_category": cat, "priority": pr, "priority_reason": str(data.get("priority_reason") or "")[:300],
        "cause": str(data.get("cause") or "")[:800], "modules": [str(m)[:30] for m in data.get("modules") or []][:6],
        "impact": str(data.get("impact") or "")[:200], "steps": [str(s)[:200] for s in data.get("steps") or []][:5],
        "summary": str(data.get("summary") or "")[:60],
        "similar_ids": [i for i in data.get("similar_ids") or [] if isinstance(i, int)][:10],
    }


# ---------------------------------------------------------------- 用户探真：境外地名译成中文

# ---------------------------------------------------------------- v3.3.87 仓库简介译成中文（截图识别结果用）

def translate_descs(descs: dict[str, str]) -> dict[str, str]:
    """{full_name: 英文简介} → {full_name: 中文简介}。已经是中文的原样返回。"""
    data = _ask(
        "把下面 GitHub 仓库的简介忠实译成通顺的简体中文，每条不超过 80 字；已经是中文的原样保留；专有名词、产品名保留英文。"
        '只输出 JSON：{"results": {"仓库全名": "中文简介"}}',
        _dump(descs), "AI-4")  # 记在截图识别名下
    res = data.get("results") or {}
    return {k: str(v)[:200] for k, v in res.items() if k in descs and isinstance(v, str) and v.strip()}


def translate_places(names: list[str]) -> dict[str, str]:
    """「United States|California|Google LLC」这类英文地名 → 中文（国家、州省、城市、运营商常用译名）。"""
    data = _ask(
        "把下面的 IP 归属地翻译成简体中文常用译名，国家/地区、省州、城市、运营商分别翻译，用 | 分隔，保持原有段数和顺序；"
        "知名公司用中文通行叫法（如 Google LLC → 谷歌，Amazon → 亚马逊），没有通行中文名的公司保留英文。"
        '只输出 JSON：{"results": {"原文": "译文"}}',
        _dump(names), "AI-geo")
    res = data.get("results") or {}
    return {k: str(v) for k, v in res.items() if k in names and isinstance(v, str) and v.strip()}


# ---------------------------------------------------------------- v3.3 评论内容审核

COMMENT_PROMPT = """你是「Skill Pocket」（AI 工具 / Skill 收录站）的评论审核员。用户在某个条目下写使用日志 / 评论，你判断能否公开。只输出 JSON：
{"decision": "pass / block / review", "category": "ok / illegal / porn / gambling / violence / abuse / ad / privacy / political / spam / other", "reason": "一句中文理由，不超过 40 字"}
标准（依据中国大陆法律法规与社区规范）：
- block：明显违法违规（色情、赌博、毒品、诈骗、暴恐、教唆犯罪、破解盗版传播）、人身攻击辱骂、广告引流（联系方式、加群、推广链接、代写代刷）、泄露他人隐私、敏感政治内容、无意义刷屏
- review：拿不准的（疑似广告、措辞激烈但不确定是否攻击、出现个人信息但不确定是否本人自愿）
- pass：正常的使用体验、问题、建议、吐槽、技术讨论（哪怕批评条目本身、带技术链接或命令，也属于正常）
宁可放过正常讨论，不要误伤。"""


def moderate_comment(content: str, item_name: str) -> dict:
    data = _ask(COMMENT_PROMPT, f"条目：{item_name}\n评论：{content[:2000]}", "AI-18", temperature=0)
    d = str(data.get("decision") or "").lower()
    return {
        "decision": d if d in ("pass", "block", "review") else "review",
        "category": str(data.get("category") or "")[:20],
        "reason": str(data.get("reason") or "")[:100],
    }
