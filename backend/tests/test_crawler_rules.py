from datetime import datetime

from app.services import crawler


class FakeGH:
    def __init__(self, paths=()):
        self.paths = list(paths)

    def tree_paths(self, full_name, branch):
        return self.paths


def repo(name, desc="", topics=()):
    return {"name": name, "full_name": f"o/{name}", "description": desc, "topics": list(topics), "default_branch": "main"}


def test_skill_by_skill_md():
    kind, dirs, _ = crawler._classify(FakeGH(["skills/a/SKILL.md", "skills/b/SKILL.md", "README.md"]), repo("my-skills"))
    assert kind == "skill" and dirs == ["skills/a", "skills/b"]


def test_skill_by_topic_without_skill_md():
    assert crawler._classify(FakeGH(), repo("x", topics=["agent-skills"]))[0] == "skill"


def test_model_and_tool_topics():
    assert crawler._classify(FakeGH(), repo("SenseVoice", topics=["asr", "speech-recognition"]))[0] == "model"
    assert crawler._classify(FakeGH(), repo("srv", topics=["mcp-server"]))[0] == "tool"


def test_hint_goes_to_review_and_unrelated_ignored():
    kind, _, note = crawler._classify(FakeGH(), repo("cool-agent", "an LLM agent for x"))
    assert kind == "review" and note
    assert crawler._classify(FakeGH(), repo("todo-app", "a simple todo list"))[0] == "ignore"


def test_window():
    t = crawler.tz()
    assert crawler.in_window(datetime(2026, 11, 2, 0, 30, tzinfo=t))
    assert not crawler.in_window(datetime(2026, 11, 2, 8, 0, tzinfo=t))
    assert crawler.window_deadline(datetime(2026, 11, 2, 9, 0, tzinfo=t)).day == 3
