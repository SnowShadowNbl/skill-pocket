// v3.3.7 详情页「复制 Prompt」：按使用类型给 AI 编程助手（Claude Code / Codex 等）不同的指令。
// 原来不管是应用还是模型都写「帮我下载安装这个 Skill」，现在分成：Agent 技能 / MCP Server / AI 模型 / 工具应用 / 开发资源 / 项目 Demo。

function isMcp(item) {
  const hay = [item.name, item.repo_full_name, item.summary, ...(item.repo?.topics || [])].join(' ').toLowerCase()
  return /\bmcp\b|mcp[-_ ]?server|model context protocol/.test(hay)
}

const PROMPTS = {
  mcp: {
    label: '复制配置 Prompt',
    text: (u) =>
      `请帮我把这个 MCP Server 配置到你（当前的 AI 助手）里：${u}\n先读 README，确认安装方式（npx / uvx / Docker 等）和需要的环境变量、API Key；缺什么先问我，不要编造。写好 MCP 配置后重启生效，并列出它提供的工具、各举一个用法例子。`,
  },
  agent_skill: {
    label: '复制安装 Prompt',
    text: (u) =>
      `请帮我安装这个 Agent Skill：${u}\n先读它的 SKILL.md 和 README，把它放到你（当前的 AI 编程助手）的 Skills 目录里；如果有依赖或需要配置的 Key，先装好依赖、缺 Key 就问我。装好后告诉我在什么情况下会触发它、能帮我做什么。`,
  },
  model: {
    label: '复制部署 Prompt',
    text: (u) =>
      `请帮我在本机部署这个开源模型：${u}\n先读 README，检查我的系统、显卡 / 显存、Python 和 CUDA 环境是否满足要求；不满足的话告诉我替代方案（量化版本、CPU 推理或官方在线 API）。然后建好独立的虚拟环境、装依赖、下载权重，跑一个最小示例验证能用，最后告诉我以后怎么调用。`,
  },
  app: {
    label: '复制安装 Prompt',
    text: (u) =>
      `请帮我安装这个工具：${u}\n先读 README，按我当前的系统选最简单的安装方式（官方安装包、Homebrew / winget、npm / pip 等），优先用官方发布的版本。装好后验证能正常启动，再用三五句话告诉我怎么开始用、常用的功能有哪些。`,
  },
  dev: {
    label: '复制接入 Prompt',
    text: (u) =>
      `我想在当前项目里用上这个开发资源：${u}\n先读 README，用几句话告诉我它解决什么问题、适不适合我这个项目；然后安装或引入依赖，在项目里写一个最小可运行的示例并跑通，说明关键的配置项。`,
  },
  demo: {
    label: '复制运行 Prompt',
    text: (u) =>
      `请帮我把这个示例项目跑起来：${u}\n克隆仓库，读 README 装好依赖、配置好需要的环境变量（缺 Key 先问我），启动后告诉我怎么访问和体验；最后简单讲讲它的关键实现，方便我参考或二次开发。`,
  },
}

/** 返回 { label, text }；没有 GitHub 地址的条目返回 null（详情页改显示「打开主页」） */
export function installPrompt(item) {
  const url = item?.github_url
  if (!url) return null
  const kind = item.kind?.key || ''
  const p = (kind === 'agent_skill' || !kind) && isMcp(item) ? PROMPTS.mcp : PROMPTS[kind] || PROMPTS.app
  return { label: p.label, text: p.text(url) }
}
