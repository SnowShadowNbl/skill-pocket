// 5 个风格 demo 共用的演示数据（中文化后的效果）
window.DEMO_GROUPS = [
  { code: 'skill', name: '技能 Skill', icon: 'puzzle', color: '#4f46e5', soft: '#eef2ff' },
  { code: 'model-audio', name: '模型 · 音频', icon: 'audio', color: '#d97706', soft: '#fff7e6' },
  { code: 'model-gen', name: '模型 · 生成', icon: 'image', color: '#db2777', soft: '#fdf0f7' },
  { code: 'tool', name: '工具', icon: 'wrench', color: '#0f766e', soft: '#e8f8f5' },
  { code: 'agent', name: '智能体', icon: 'bot', color: '#16a34a', soft: '#ecfdf3' },
  { code: 'dev', name: '开发资源', icon: 'package', color: '#7c3aed', soft: '#f4f0ff' },
]

window.DEMO_ITEMS = [
  {
    id: 1, name: 'pdf', group: 'skill', cat: '文档办公', stars: 186582, delta: 1526, source: 'auto', lang: 'Python', license: 'Apache-2.0',
    summary: '处理 PDF 的全能 Skill：提取文字和表格、合并拆分、填写表单、OCR 扫描件。',
    desc: '让 Claude 在对话中直接处理 PDF 文件。支持读取正文与表格、合并或拆分多个 PDF、旋转页面、添加水印、加解密，以及对扫描件做 OCR 让其可搜索。\n\n适合需要批量整理合同、报表、论文的场景，配合 Python 库在本地完成，不需要上传文件到第三方服务。',
    steps: [
      { title: '克隆仓库', cmd: 'git clone https://github.com/anthropics/skills.git' },
      { title: '复制到 Claude Code 的 skills 目录', cmd: 'cp -r skills/skills/pdf ~/.claude/skills/pdf' },
      { title: '重启 Claude Code，提到 PDF 时自动触发', cmd: '' },
    ],
  },
  {
    id: 2, name: 'SenseVoice', group: 'model-audio', cat: '语音识别 ASR', stars: 9668, delta: 214, source: 'auto', lang: 'Python', license: 'MIT',
    summary: '多语言语音理解模型，中文识别准确，附带情感识别和音频事件检测。',
    desc: 'SenseVoice 是一个语音基础模型，同时支持自动语音识别（ASR）、语种识别、语音情感识别和音频事件检测。\n\n推理速度非常快，适合在 CPU 上部署做准实时转写，对中文、粤语、英语、日语、韩语都有很好的效果。',
    steps: [
      { title: '安装依赖', cmd: 'pip install funasr modelscope' },
      { title: '下载模型并识别音频', cmd: 'python -m funasr.bin.inference --model iic/SenseVoiceSmall --input demo.wav' },
    ],
  },
  {
    id: 3, name: 'skill-creator', group: 'skill', cat: 'Skill 开发', stars: 186582, delta: 1526, source: 'manual', lang: 'Python', license: 'Apache-2.0',
    summary: '帮你创建、测试和迭代新 Skill 的元 Skill，带评测与描述优化。',
    desc: '从零创建新的 Skill，或改进已有 Skill。它会引导你写好 SKILL.md、准备测试用例、跑评测并对比效果，还能自动优化 Skill 的触发描述。\n\n适合想把团队流程沉淀成 Skill 的人。',
    steps: [
      { title: '复制到 skills 目录', cmd: 'cp -r skills/skills/skill-creator ~/.claude/skills/' },
      { title: '对 Claude 说“帮我做一个 Skill”即可开始', cmd: '' },
    ],
  },
  {
    id: 4, name: 'FLUX', group: 'model-gen', cat: '文生图', stars: 25310, delta: 388, source: 'auto', lang: 'Python', license: 'Apache-2.0',
    summary: '高质量开源文生图模型，提示词理解强，细节和文字渲染出色。',
    desc: 'FLUX 是新一代开源图像生成模型，在提示词遵循、画面细节、手部与文字渲染上表现突出。\n\n提供多个版本，可在消费级显卡上运行精简版，也能通过 diffusers 快速集成。',
    steps: [
      { title: '安装 diffusers', cmd: 'pip install -U diffusers torch' },
      { title: '运行官方示例脚本', cmd: 'python -m flux --name flux-schnell --prompt "一只坐在窗边的橘猫"' },
    ],
  },
  {
    id: 5, name: 'MCP Servers', group: 'tool', cat: 'MCP Server', stars: 78400, delta: 902, source: 'auto', lang: 'TypeScript', license: 'MIT',
    summary: 'Model Context Protocol 官方服务器合集：文件系统、Git、数据库等开箱即用。',
    desc: '官方维护的 MCP Server 参考实现合集，让 AI 助手安全地访问文件系统、Git 仓库、数据库、网页抓取等能力。\n\n每个服务器都可以独立安装，在 Claude Desktop 或 Claude Code 的配置中启用即可。',
    steps: [
      { title: '以文件系统服务器为例', cmd: 'npx -y @modelcontextprotocol/server-filesystem ~/Documents' },
      { title: '在客户端配置中添加该服务器', cmd: '' },
    ],
  },
  {
    id: 6, name: 'ollama', group: 'dev', cat: '推理部署', stars: 186001, delta: 640, source: 'manual', lang: 'Go', license: 'MIT',
    summary: '一行命令在本地运行 Qwen、DeepSeek、Gemma 等开源大模型。',
    desc: 'Ollama 让你在自己的电脑上轻松运行开源大模型，自动处理模型下载、量化和 GPU 加速，并提供兼容 OpenAI 的 API。\n\n适合本地开发、离线使用和隐私敏感的场景。',
    steps: [
      { title: '安装 Ollama', cmd: 'curl -fsSL https://ollama.com/install.sh | sh' },
      { title: '运行模型', cmd: 'ollama run qwen3' },
    ],
  },
  {
    id: 7, name: 'CosyVoice', group: 'model-audio', cat: '语音合成 TTS', stars: 17200, delta: 156, source: 'auto', lang: 'Python', license: 'Apache-2.0',
    summary: '多语言语音合成，几秒音频即可克隆音色，支持情感和方言控制。',
    desc: 'CosyVoice 是开源的语音生成模型，支持零样本音色克隆、跨语种合成和细粒度情感控制。\n\n流式合成延迟低，适合做数字人、有声书和语音助手。',
    steps: [
      { title: '克隆仓库并安装依赖', cmd: 'git clone https://github.com/FunAudioLLM/CosyVoice.git && pip install -r requirements.txt' },
      { title: '启动网页演示', cmd: 'python webui.py --port 50000' },
    ],
  },
  {
    id: 8, name: 'browser-use', group: 'agent', cat: '浏览器智能体', stars: 72100, delta: 1203, source: 'auto', lang: 'Python', license: 'MIT',
    summary: '让 AI 像人一样操作浏览器：点击、填表、跨页面完成任务。',
    desc: 'browser-use 把网页转换成大模型可以理解的结构，让 Agent 自主完成订票、比价、表单填写等多步骤网页任务。\n\n支持多种模型，可以本地运行也可以接入云端浏览器。',
    steps: [
      { title: '安装', cmd: 'pip install browser-use' },
      { title: '安装浏览器内核', cmd: 'playwright install chromium' },
    ],
  },
  {
    id: 9, name: 'frontend-design', group: 'skill', cat: '设计创意', stars: 186582, delta: 1526, source: 'manual', lang: 'Python', license: 'Apache-2.0',
    summary: '让 AI 做出有设计感的前端页面，避免千篇一律的“AI 味”。',
    desc: '在编写前端界面之前加载，引导 AI 先确定设计方向（字体、配色、版式、动效），再落地为代码，产出有辨识度的页面。\n\n适合着陆页、产品页和设计原型。',
    steps: [{ title: '复制到 skills 目录', cmd: 'cp -r skills/skills/frontend-design ~/.claude/skills/' }],
  },
]
