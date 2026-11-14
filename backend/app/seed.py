"""分类字典与使用类型。

两个互不重叠的维度：
- 领域分类（两级，存 categories 表）：它用在什么事上，如「语音与音频 › 语音识别」
- 使用类型（固定 5 类，存 items.kind）：谁来用、怎么用，如「AI 模型」

v1.3 起领域分类换成第 2 版（TAXONOMY_VERSION）。旧版里按形态分的大类（技能 / 工具 / 开发资源）停用，
含义相同的子类保留原 code（榜单历史得以延续）。之后按 code 幂等补充：已存在的不覆盖（管理员可能改过名字）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppMeta, Category

TAXONOMY_VERSION = "2"

# (大类 code, 名称, 图标, [(子类 code, 名称, 说明)])
CATEGORIES = [
    ("coding", "编程开发", "💻", [
        ("coding-gen", "代码生成", "写代码、补全、重构、脚手架、前端实现"),
        ("coding-review", "代码评审与测试", "Code Review、单元测试、调试、安全审计"),
        ("coding-assistant", "编程助手", "编程智能体、AI IDE、Claude Code / Codex 增强"),
        ("coding-toolchain", "开发工具链", "Git、命令行、IDE 插件、部署运维、API 开发"),
    ]),
    ("office", "文档办公", "📄", [
        ("office-docs", "文档处理", "Word / PPT / Excel / PDF 的生成、编辑、转换"),
        ("model-ocr", "OCR 与文档解析", "文字识别、版面分析、PDF 解析"),
        ("office-notes", "笔记与知识管理", "笔记、知识库整理、会议纪要、个人效率"),
    ]),
    ("writing", "写作内容", "✍️", [
        ("writing-copy", "文案写作", "营销文案、邮件、报告、润色"),
        ("writing-translate", "翻译", "文本翻译、本地化、字幕翻译"),
        ("writing-content", "内容创作", "博客、社媒、视频脚本、小说"),
    ]),
    ("image", "图像设计", "🎨", [
        ("model-text2image", "文生图", "如 FLUX、Stable Diffusion"),
        ("model-image-edit", "图像编辑", "修图、风格化、超分、抠图"),
        ("design-ui", "UI 与设计", "UI / UX、海报、品牌规范、画布、设计稿转代码"),
        ("model-3d", "3D 生成", "文 / 图生 3D"),
    ]),
    ("video", "视频", "🎬", [
        ("model-text2video", "视频生成", "如 Wan、HunyuanVideo"),
        ("model-video-understanding", "视频理解", "视频问答、视频描述、剪辑辅助"),
        ("model-digital-human", "数字人", "口型驱动、虚拟形象"),
    ]),
    ("audio", "语音与音频", "🎙️", [
        ("model-asr", "语音识别", "如 FunASR、SenseVoice、Whisper"),
        ("model-tts", "语音合成", "如 CosyVoice、F5-TTS"),
        ("model-voice-clone", "声音克隆", "音色克隆、实时变声"),
        ("model-music", "音乐音效", "音乐生成、音效生成、人声分离"),
        ("model-audio-understanding", "音频理解", "音频问答、情感、声纹"),
    ]),
    ("vision", "视觉理解", "👁️", [
        ("model-vlm", "多模态理解", "图文理解、视觉问答"),
        ("model-detection", "检测与分割", "目标检测、分割、姿态"),
        ("model-face", "人像与人脸", "人脸识别、换脸、人像处理"),
    ]),
    ("language", "语言模型", "🧠", [
        ("model-llm-general", "通用大模型", "如 Qwen、DeepSeek、Llama"),
        ("model-llm-code", "代码模型", "如 Qwen-Coder、DeepSeek-Coder"),
        ("model-llm-reasoning", "推理模型", "长思维链 / 推理增强模型"),
        ("model-llm-small", "端侧小模型", "可在手机 / 边缘设备运行"),
        ("model-embedding", "向量与重排", "Embedding / Reranker"),
    ]),
    ("agent", "智能体与自动化", "🤖", [
        ("agent-framework", "Agent 框架", "多智能体、Agent SDK、记忆"),
        ("agent-workflow", "工作流编排", "可视化 / 代码式工作流"),
        ("agent-browser", "浏览器 / 桌面自动化", "操作浏览器、桌面、手机，网页抓取"),
        ("agent-rag", "RAG 与知识库", "检索增强、知识库问答"),
        ("agent-connector", "连接器与集成", "MCP、第三方服务接入、数据源连接"),
    ]),
    ("research", "数据与研究", "📊", [
        ("data-analysis", "数据分析", "数据清洗、SQL、图表、报表"),
        ("data-research", "研究检索", "调研、搜索、论文、文献整理"),
    ]),
    ("infra", "AI 基础设施", "⚙️", [
        ("dev-inference", "推理部署", "如 vLLM、Ollama、llama.cpp"),
        ("dev-finetune", "训练微调", "微调、RLHF、训练框架"),
        ("dev-dataset", "数据集", "训练 / 评测数据集"),
        ("dev-eval", "评测基准", "Benchmark、评测工具"),
    ]),
    ("ecosystem", "Skill 生态", "🧰", [
        ("skill-meta", "Skill 开发与管理", "创建 / 测试 / 分发 / 管理 Skill 的工具与 Skill"),
        ("dev-awesome", "精选清单", "awesome-xxx、Skill 合集等资源汇总"),
    ]),
    ("other", "其他", "📁", [
        ("other-misc", "其他", "兜底分类"),
    ]),
]

FALLBACK_CODE = "other-misc"
SKILL_FALLBACK_CODE = "coding-gen"

# 使用类型：从“谁来用、怎么用”的角度
KINDS = {
    "agent_skill": ("Agent 技能", "🧩", "装给 AI Agent 用的能力，人不直接操作：SKILL.md、Claude / Codex Skills、MCP Server、Agent 插件、规则或 Prompt 包"),
    "model": ("AI 模型", "🧠", "需要下载权重运行或通过接口调用的模型：大语言模型、语音识别 / 合成、文生图、检测模型等"),
    "app": ("工具应用", "🛠️", "普通人直接上手使用的成品：桌面 / 网页应用、命令行工具、浏览器插件、IDE 插件"),
    "dev": ("开发资源", "📦", "开发者搭建 AI 应用用的底层材料：框架、SDK、推理部署、训练微调、数据集、评测基准、精选清单"),
    "demo": ("项目 Demo", "🧪", "示例、教程、原型或实验项目，拿来参考或二次开发，不是成品"),
}


def _meta(db: Session, key: str) -> str | None:
    m = db.get(AppMeta, key)
    return m.value if m else None


def _apply_taxonomy(db: Session, existing: dict[str, Category]) -> None:
    """切换到当前版本的分类树：按定义写入名称 / 父级 / 排序，定义之外的分类停用（保留历史榜单）。"""
    wanted = set()
    for g_sort, (g_code, g_name, g_icon, children) in enumerate(CATEGORIES):
        group = existing.get(g_code) or Category(code=g_code)
        group.parent_id, group.name, group.icon, group.sort, group.enabled = None, g_name, g_icon, g_sort * 10, True
        db.add(group)
        db.flush()
        existing[g_code] = group
        wanted.add(g_code)
        for c_sort, (c_code, c_name, c_remark) in enumerate(children):
            c = existing.get(c_code) or Category(code=c_code)
            c.parent_id, c.name, c.remark, c.sort, c.enabled = group.id, c_name, c_remark, c_sort * 10, True
            db.add(c)
            existing[c_code] = c
            wanted.add(c_code)
    for code, c in existing.items():
        if code not in wanted:
            c.enabled = False
    db.merge(AppMeta(key="taxonomy", value=TAXONOMY_VERSION))


def seed_categories(db: Session) -> bool:
    """返回本次是否切换了分类树版本（切换后需要对存量条目重新分类）。"""
    existing = {c.code: c for c in db.scalars(select(Category))}
    switched = _meta(db, "taxonomy") != TAXONOMY_VERSION
    if switched:
        _apply_taxonomy(db, existing)
        db.commit()
        return True

    for g_sort, (g_code, g_name, g_icon, children) in enumerate(CATEGORIES):
        group = existing.get(g_code)
        if group is None:
            group = Category(code=g_code, name=g_name, icon=g_icon, sort=g_sort * 10)
            db.add(group)
            db.flush()
        for c_sort, (c_code, c_name, c_remark) in enumerate(children):
            if c_code not in existing:
                db.add(Category(parent_id=group.id, code=c_code, name=c_name, remark=c_remark, sort=c_sort * 10))
    db.commit()
    return False
