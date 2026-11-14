from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")
    # 启动时是否自动重画旧主题的 AI 封面（本地开发可关掉，免得花额度）
    cover_redraw_on_start: bool = True

    # 本地默认 SQLite；生产改为 postgresql+psycopg://user:pass@host/db
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'skillhub.db').as_posix()}"
    media_dir: Path = BASE_DIR / "data" / "media"
    frontend_dist: Path = BASE_DIR.parent / "frontend" / "dist"

    # 管理员：只存 bcrypt 哈希，用 `python -m app.cli set-password` 生成
    admin_password_hash: str = ""
    secret_key: str = "dev-secret-change-me"
    admin_session_minutes: int = 30
    login_max_fails: int = 5
    login_lock_minutes: int = 15

    github_token: str = ""
    # 页脚「联系站长」邮箱；为空不显示
    contact_email: str = ""

    # OpenAI 兼容接口；不配置时走规则兜底提炼
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_text_model: str = ""

    cors_origins: str = "http://localhost:5173"

    # 语音转文字（FunASR 2pass 流式 websocket），如 ws://funasr:10095；为空时语音评论按钮置灰
    funasr_ws_url: str = ""

    # ---- 自动采集（P2） ----
    crawl_enabled: bool = True
    crawl_tz: str = "Asia/Shanghai"
    # 工作窗口：开始时刻跑快照和榜单，额度用完就等下一小时重置，到结束时刻还没跑完的留到第二天
    crawl_start: str = "00:05"
    crawl_end: str = "08:00"
    rank_top_n: int = 10
    max_new_repos_per_run: int = 60
    # 自动采集时 SKILL.md 超过这个数的仓库视为“合集”，只收一个条目（手动导入不受限）
    skill_split_max: int = 15
    trending_enabled: bool = True
    # 逗号分隔；GitHub Search 语法
    discovery_queries: str = (
        "topic:claude-skills,topic:agent-skills,topic:claude-code-skills,topic:mcp-server stars:>200,"
        "topic:speech-recognition stars:>500,topic:text-to-speech stars:>500,topic:text-to-image stars:>1000,"
        "topic:llm stars:>3000,topic:ai-agents stars:>2000"
    )
    # 逗号分隔的 awesome 清单仓库（owner/repo），从 README 里提取仓库链接
    awesome_lists: str = ""

    @property
    def crawl_queries(self) -> list[str]:
        return [q.strip() for q in self.discovery_queries.split(",") if q.strip()]

    @property
    def awesome_repos(self) -> list[str]:
        return [q.strip() for q in self.awesome_lists.split(",") if q.strip()]

    # 界面 AI 标签显示的模型名：逗号分隔的「模型 id=显示名」
    ai_model_labels: str = "deepseek-flash=DeepSeek-V4.1-Flash,deepseek-chat=DeepSeek-V3,deepseek-reasoner=DeepSeek-R1"
    asr_model_label: str = "FunASR-Paraformer"

    # ---- v1.3 搜索添加 / 长文识别 ----
    # GitHub 搜索接口带 Token 时每分钟 30 次，全站共用，留余量给夜间采集
    search_per_minute: int = 25
    # 单个访客（P1 按 IP）每分钟可发起的查找次数
    finder_per_minute: int = 6
    text_max_chars: int = 50000

    # ---- v2.0 用户体系 ----
    session_days: int = 30
    # 腾讯云邮件推送 SES（未配置密钥时验证码只打印在服务端日志里，仅限本地开发）
    ses_secret_id: str = ""
    ses_secret_key: str = ""
    ses_region: str = "ap-guangzhou"
    ses_from: str = ""
    ses_template_id: int = 0
    # 本地开发：接口直接返回验证码（生产环境必须为 false）
    auth_dev_codes: bool = False
    # v3.3.55 后台高危操作（导出含邮箱、改用户邮箱、删除用户、任免管理员）需要邮箱验证码二次验证。
    # v3.3.56 管理端已接好验证弹窗，默认打开
    admin_verify_required: bool = True
    code_ttl_minutes: int = 10
    code_resend_seconds: int = 60
    code_per_email_daily: int = 10
    code_per_ip_daily: int = 30
    email_daily_limit: int = 500  # 全站每日发信上限，防止被刷费用

    # ---- v3.1 微信小程序登录（code2session）----
    wx_appid: str = ""
    wx_secret: str = ""
    # v3.3.9 网页微信扫码用的小程序码打开哪个版本：release 正式版 / trial 体验版 / develop 开发版（小程序还没发布时用 trial）
    wx_qr_env: str = "release"
    # 发验证码前的人机校验（工作量证明）难度：前导零比特数
    pow_bits: int = 18
    # 普通用户每天可发起的 AI 识别 / 搜索次数（截图识别 + 长文识别 + 搜索添加）
    daily_ai_quota: int = 30

    # 语义搜索：Embedding 接口（OpenAI 兼容），默认阿里云百炼北京地域
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dims: int = 1024

    # 资源监控：DeepSeek 余额低于这个数（元）时提醒充值；百炼向量的免费额度与单价（无法用 API Key 查余额，用来估算）；
    # 腾讯云邮件推送每月额度（0 表示不显示额度进度）
    ai_balance_warn: float = 10.0
    embedding_free_tokens: int = 1_000_000
    embedding_price_per_1k_tokens: float = 0.0005
    # v3.3.59 后台「AI 与成本」：各模型单价（元 / 百万 token），JSON：{"模型名": [输入单价, 输出单价]}；没配的模型成本显示「未知」
    ai_prices: str = ""
    # 额度余额低于这个数（用户侧额度）算「余额不足」
    quota_low_threshold: int = 200_000
    # v3.3.64 运行监控：数据库备份所在目录（docker-compose 把宿主机的 backups 只读挂到这里）
    backup_dir: str = "/app/backups"
    ses_monthly_quota: int = 0

    # IP 归属地：离线 ip2region 库缺失时自动从 GitHub 下载（测试里关掉）
    geo_download: bool = True

    # 每日失效巡检的并发与单次上限
    liveness_max_items: int = 5000

    @property
    def ses_enabled(self) -> bool:
        return bool(self.ses_secret_id and self.ses_secret_key and self.ses_template_id and self.ses_from)

    @property
    def model_labels(self) -> dict[str, str]:
        out = {}
        for pair in self.ai_model_labels.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_base_url and self.ai_api_key and self.ai_text_model)


settings = Settings()
