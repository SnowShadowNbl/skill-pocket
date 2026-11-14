"""v1.3：AI 研判相关的流程（AI 调用用替身，不访问外网）。"""

import time

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import AppMeta, Category, FinderJob
from app.seed import seed_categories
from app.services import blurbs, crawler, finder, judge


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


# ---------------------------------------------------------------- 分类树切换

def test_taxonomy_switch_reuses_codes_and_disables_old():
    with SessionLocal() as s:
        s.merge(AppMeta(key="taxonomy", value="1"))
        old = Category(code="tool-cli", name="命令行工具")
        s.add(old)
        s.commit()
        assert seed_categories(s) is True
        assert s.scalar(select(Category).where(Category.code == "tool-cli")).enabled is False
        asr = s.scalar(select(Category).where(Category.code == "model-asr"))
        assert asr.enabled and asr.parent.code == "audio"
        assert seed_categories(s) is False  # 已是当前版本


# ---------------------------------------------------------------- 自动采集筛选

class FakeGH:
    def tree_paths(self, full_name, branch):
        return [f"skills/s{i}/SKILL.md" for i in range(8)] if "skills" in full_name else []


def test_screening_uses_ai_verdicts(monkeypatch):
    verdicts = [
        {"relevant": True, "confidence": 0.9, "kind": "model", "reason": "开源语音模型"},
        {"relevant": False, "confidence": 0.95, "kind": "", "reason": "普通网站"},
        {"relevant": True, "confidence": 0.4, "kind": "app", "reason": "看不太出"},
        {"relevant": True, "confidence": 0.9, "kind": "agent_skill", "reason": "一组 Skill"},
    ]
    monkeypatch.setattr(judge, "screen_repos", lambda repos: verdicts[: len(repos)])
    monkeypatch.setattr(judge, "judge_collection", lambda *a: ("split", "同一作者维护"))
    batch = [{"full_name": n, "name": n.split("/")[1]} for n in ("a/asr", "b/site", "c/thing", "d/skills")]
    out = crawler._judge_batch(FakeGH(), batch)
    assert [o[0] for o in out] == ["accept", "ignore", "review", "accept"]
    assert out[0][3] == "model" and len(out[3][1]) == 8
    assert crawler._split_mode(batch[3], out[3][1]) == (True, "AI：同一作者维护")


def test_screening_falls_back_to_rules_without_ai():
    out = crawler._judge_batch(FakeGH(), [{"full_name": "o/x", "name": "x", "topics": ["asr"], "description": ""}])
    assert out[0][0] == "accept" and out[0][3] == "model"


# ---------------------------------------------------------------- 榜单详解的「大改」判断

def test_blurb_major_change_detection():
    base = blurbs.doc_basis("# Tool\n\n![badge](x.svg)\nA fast speech recognizer.\n\n## Install\npip install tool\n" * 5)
    tweak = blurbs.doc_basis("# Tool\n\n![badge](y.svg)\nA fast speech recognizer!\n\n## Install\npip install tool\n" * 5)
    rewrite = blurbs.doc_basis("# Tool 2.0\n\nNow a full meeting assistant with diarization, summaries and a web UI.\n" * 5)
    assert not blurbs.changed_a_lot(base, tweak)
    assert blurbs.changed_a_lot(base, rewrite)
    assert blurbs.changed_a_lot("", base)


# ---------------------------------------------------------------- 长文识别的文本处理

def test_links_chunks_and_html():
    text = "推荐 https://github.com/anthropics/skills/tree/main/skills/pdf 和 github.com/FunAudioLLM/SenseVoice。" \
           "还有 https://github.com/topics/ai 不算"
    text += "，见 github.com/browser-use/browser-use。还有 https://github.com/a/b.git）"
    links = finder.github_links(text)
    assert links == [{"repo": "anthropics/skills", "sub_path": "skills/pdf"}, {"repo": "FunAudioLLM/SenseVoice", "sub_path": None},
                     {"repo": "browser-use/browser-use", "sub_path": None}, {"repo": "a/b", "sub_path": None}]
    # 链接后紧跟全角标点
    assert finder.github_links("（https://github.com/anthropics/skills/tree/main/skills/pdf），处理")[0]["sub_path"] == "skills/pdf"
    parts = finder.chunks("段落\n" * 5000)
    assert len(parts) > 1 and all(len(p) <= finder.CHUNK_CHARS for p in parts)
    page = '<html><script>x()</script><div id="js_content"><p>看 <a href="https://github.com/a/b">这个</a>&amp;</p></div></html>'
    assert finder.html_to_text(page) == "看 这个 (https://github.com/a/b)&"


# ---------------------------------------------------------------- 搜索添加

class FakeSearchGH:
    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def search_repos(self, q, per_page=30, sort="stars"):
        base = {"html_url": "", "language": "Python", "topics": [], "default_branch": "main"}
        return {
            "face recognition model": [{**base, "full_name": "x/face-rec", "description": "face recognition", "stargazers_count": 900},
                                       {**base, "full_name": "y/todo", "description": "todo app", "stargazers_count": 50}],
            "insightface": [{**base, "full_name": "deepinsight/insightface", "description": "2D/3D face", "stargazers_count": 25000}],
        }.get(q, [])

    def tree_paths(self, *a):
        return []


def test_search_flow(monkeypatch):
    monkeypatch.setattr(finder, "GitHub", FakeSearchGH)
    monkeypatch.setattr(judge, "plan_search", lambda q, avoid=None: {
        "intent": "feature", "kind": "model", "understanding": "找人脸识别模型",
        "queries": ["face recognition model", "insightface"], "skill_queries": []})
    monkeypatch.setattr(judge, "rerank", lambda need, cands: {
        "deepinsight/insightface": {"score": 95, "kind": "model", "reason": "主流人脸识别库"},
        "x/face-rec": {"score": 70, "kind": "model", "reason": "人脸识别模型"},
        "y/todo": {"score": 5, "kind": "app", "reason": "无关"},
    })
    job_id = finder.create_job("search", "我想要个人像识别的模型")
    finder.run_search(job_id)
    with SessionLocal() as s:
        job = s.get(FinderJob, job_id)
        assert job.status == "done", job.result
        names = [c["full_name"] for c in job.result["candidates"]]
    assert names == ["deepinsight/insightface", "x/face-rec"]  # 无关结果被过滤，按相关度排序


def test_search_needs_ai_for_chinese():
    # 上一个用例的搜索方案已缓存，这里换一句没搜过的
    job_id = finder.create_job("search", "帮我找个能自动写周报的工具")
    finder.run_search(job_id)
    with SessionLocal() as s:
        job = s.get(FinderJob, job_id)
        assert job.status == "failed" and "AI" in job.result["error"]
