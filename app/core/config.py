"""Application configuration.

A single typed settings object, populated from environment variables (and the
local ``.env`` file in development). Import ``settings`` everywhere; never read
``os.environ`` directly.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_env: str = "development"
    app_name: str = "xuanwu"
    app_version: str = "0.1.0"
    git_tag: str = "unknown"  # set at build time (CI)
    git_sha: str = "unknown"  # set at build time (CI)
    log_level: str = "info"
    cors_origins: str = "http://localhost:3000"  # comma-separated
    first_user_superadmin: bool = True  # the very first registered user becomes superadmin

    # --- Database (MySQL 8) ---
    database_url: str
    database_url_sync: str

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    celery_task_always_eager: bool = False  # run tasks inline (tests/dev without a worker)

    # --- GeoIP (audit trail country resolution) ---
    geoip_provider: str = "none"  # none | maxmind
    geoip_db_path: str = "config/geoip/GeoLite2-Country.mmdb"

    # --- Crypto / secrets ---
    secret_key: str
    blind_index_key: str
    jwt_private_key_path: str = "config/keys/jwt_private.pem"
    jwt_public_key_path: str = "config/keys/jwt_public.pem"

    # --- JWT ---
    jwt_issuer: str = "xuanwu"
    jwt_audience: str = "xuanwu"

    # --- Token / session policy ---
    access_token_ttl: int = 900  # 15 minutes
    refresh_token_ttl: int = 604800  # 7 days
    login_max_attempts: int = 5
    login_lockout_ttl: int = 900  # 15 minutes

    # --- Auth cookies ---
    access_cookie_name: str = "access_token"
    refresh_cookie_name: str = "refresh_token"
    csrf_cookie_name: str = "csrf_token"
    cookie_secure: bool = False  # True in production (HTTPS)
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- Password policy ---
    password_min_length: int = 8
    password_max_length: int = 80
    password_min_score: int = 2  # zxcvbn 0..4

    # --- TOTP / API keys ---
    totp_issuer: str = "Xuanwu"
    api_key_nonce_window_ms: int = 5000

    # --- Authorization (RBAC) ---
    authz_rules_path: str = "config/authz_rules.yml"
    permission_cache_ttl: int = 300  # 5 minutes

    # --- Progressive verification (levels & state triggers) ---
    auth_config_path: str = "config/auth.yml"

    # --- Email ---
    email_provider: str = "smtp"  # mock | smtp | sendgrid
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    email_from: str = "no-reply@rarevintage.com.au"
    email_from_name: str = "Rare Vintage"
    email_default_language: str = "en"
    mailer_config_path: str = "config/mailer.yml"  # event-key → template/subject registry
    sendgrid_api_key: str = ""
    frontend_url: str = "http://localhost:3000"  # base URL for links in emails

    # --- SMS ---
    sms_provider: str = "mock"  # mock | twilio_sms | twilio_verify | aws_sns
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""  # E.164 sender, e.g. +61400000000
    twilio_service_sid: str = ""  # Twilio Verify service SID (twilio_verify only)
    aws_region: str = "ap-southeast-2"
    sms_content_template: str = "Your Rare Vintage verification code is {code}."
    sms_code_ttl: int = 600  # seconds a verification code stays valid

    # --- Object storage ---
    storage_provider: str = "local"  # local | s3
    upload_dir: str = "uploads"  # local provider base directory
    upload_max_size: int = 10_485_760  # 10 MB
    upload_extensions: str = "pdf,jpg,jpeg,png"  # comma-separated allowlist
    s3_endpoint_url: str = "http://minio:9000"  # blank for real AWS S3
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "xuanwu-dev"
    s3_region: str = "us-east-1"
    s3_url_expiration: int = 3600  # presigned URL lifetime (seconds)
    s3_sse: str = "AES256"  # server-side encryption; blank to disable (e.g. MinIO)

    @property
    def upload_extensions_list(self) -> list[str]:
        return [e.strip().lower() for e in self.upload_extensions.split(",") if e.strip()]

    # --- Citizen mobile login (prototype) ---
    # Any valid Indian mobile + this fixed code logs in; refused when APP_ENV=production.
    prototype_otp: str = "1111"

    # --- LLM (scheme assistant) ---
    llm_provider: str = "mock"  # mock | gemini
    gemini_api_key: str = ""
    llm_model: str = "gemini-3.5-flash"  # answers
    # Used when the main model is overloaded or rate-limited (spec §8). Blank = no fallback.
    llm_fallback_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: float = 45.0
    llm_history_messages: int = 12  # previous messages sent as context
    # Gemini counts hidden "thinking" tokens against this cap too, so leave headroom.
    llm_max_output_tokens: int = 4096
    # Gemini 3 "thinking" spends hidden tokens; "low" keeps answers fast and cheap.
    llm_thinking_level: str = "low"  # low | high

    # --- Speech-to-text (voice messages) ---
    # Blank = same as LLM_PROVIDER, so a server with a real LLM never silently
    # transcribes with the mock (which returns one fixed sentence).
    stt_provider: str = ""  # "" | mock | gemini (uses GEMINI_API_KEY)
    stt_model: str = ""  # blank = LLM_MODEL; LLM_FALLBACK_MODEL is tried on overload
    stt_max_bytes: int = 5_242_880  # 5 MB, about 5 minutes of compressed speech
    stt_max_seconds: int = 120  # the browser stops recording here too
    # How long a transcript stays valid before it must be sent with a message.
    stt_token_ttl: int = 1800
    # Words on screen while the citizen talks (Gemini Live API). Off = upload after.
    stt_live_enabled: bool = True
    stt_live_model: str = "gemini-3.5-transcribe-live"
    stt_live_per_minute: int = 20  # live sessions per user per minute

    # --- Text-to-speech (spoken replies) ---
    tts_provider: str = ""  # "" = same as LLM_PROVIDER | mock | gemini
    tts_model: str = "gemini-3.8-flash-lite-tts"  # fastest; Punjabi reads well
    tts_fallback_model: str = "gemini-3.8-flash-tts"  # on overload / rate limit
    tts_voice: str = "Kore"  # Gemini prebuilt voice
    tts_max_chars: int = 1500  # longer replies are cut at a sentence end

    # --- Scheme search (embeddings) ---
    # Small knowledge bases are sent to the model whole; above this many active
    # schemes the assistant first shortlists the relevant ones by meaning.
    embedding_provider: str = ""  # "" = same as LLM_PROVIDER | mock | gemini
    embedding_model: str = "gemini-embedding-2"  # multilingual: Punjabi query, English data
    embedding_dimensions: int = 768
    scheme_full_injection_limit: int = 25
    scheme_shortlist_size: int = 12

    # --- Official-website search (when a scheme is not in the verified list) ---
    # Only answers backed by official Indian government pages are shown, labelled
    # as not verified by us. Gemini's Google Search tool is used; the domain
    # allowlist is enforced in our code (official_search.is_official).
    websearch_provider: str = ""  # "" = same as LLM_PROVIDER | mock | gemini | none (off)
    websearch_model: str = ""  # "" = LLM_MODEL
    websearch_timeout_seconds: float = 15.0  # the citizen sees a "checking" animation meanwhile
    websearch_cache_seconds: int = 86400  # same question, same language: reuse for a day
    # Hostname suffixes that count as official. Anything else is dropped.
    websearch_allowed_domains: str = "gov.in,nic.in"

    # --- Captcha ---
    captcha_provider: str = "none"  # none | recaptcha
    recaptcha_secret: str = ""
    recaptcha_site_key: str = ""

    # --- Rate limiting & hardening ---
    rate_limit_enabled: bool = True
    rate_limit_default: str = "300/minute"  # global per-IP ceiling
    rate_limit_login: str = "10/minute"  # extra ceiling on the login endpoint
    rate_limit_voice: str = "20/minute"  # speech-to-text is a paid call per clip
    rate_limit_speech: str = "30/minute"  # text-to-speech, likewise
    rate_limit_websearch: str = "10/minute"  # official-website search, a paid call
    hsts_enabled: bool = False  # send Strict-Transport-Security (set True behind HTTPS)

    @property
    def stt_provider_name(self) -> str:
        return (self.stt_provider or self.llm_provider).lower()

    @property
    def tts_provider_name(self) -> str:
        return (self.tts_provider or self.llm_provider).lower()

    @property
    def embedding_provider_name(self) -> str:
        return (self.embedding_provider or self.llm_provider).lower()

    @property
    def websearch_provider_name(self) -> str:
        return (self.websearch_provider or self.llm_provider).lower()

    @property
    def websearch_allowed_suffixes(self) -> list[str]:
        return [
            d.strip().lower().lstrip(".")
            for d in self.websearch_allowed_domains.split(",")
            if d.strip()
        ]

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    # Values are supplied at runtime via the environment / .env file.
    return Settings()


settings = get_settings()
