from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr

BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BASE_DIR.parent.parent


class Settings(BaseSettings):
    app_env: str = "development"
    app_public_base_url: str = "http://localhost:3000"
    max_upload_size_mb: int = 20
    price_per_file_vnd: int = 19000

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_base_url: str = ""

    payos_api_base_url: str = "https://api-merchant.payos.vn"
    payos_client_id: str = ""
    payos_api_key: str = ""
    payos_checksum_key: str = ""
    payos_link_ttl_minutes: int = 30
    download_token_ttl_minutes: int = 15
    fixed_file_payment_required: bool = False

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BASE_DIR / ".env"),
        env_file_encoding="utf-8-sig",
        env_ignore_empty=True,
        extra="ignore",
    )

    
    supabase_anon_key: SecretStr = Field(
        alias="SUPABASE_ANON_KEY"
    )

    upstash_redis_rest_url: str = Field(
        alias="UPSTASH_REDIS_REST_URL"
    )

    upstash_redis_rest_token: SecretStr = Field(
        alias="UPSTASH_REDIS_REST_TOKEN"
    )

    auth_rate_limit_hmac_secret: SecretStr = Field(
        alias="AUTH_RATE_LIMIT_HMAC_SECRET"
    )

    frontend_auth_callback_url: str = Field(
        alias="FRONTEND_AUTH_CALLBACK_URL"
    )

    registration_ip_limit: int = Field(
        default=5,
        alias="REGISTRATION_IP_LIMIT"
    )

    registration_ip_window_seconds: int = Field(
        default=900,
        alias="REGISTRATION_IP_WINDOW_SECONDS"
    )

    registration_email_limit: int = Field(
        default=3,
        alias="REGISTRATION_EMAIL_LIMIT"
    )

    registration_email_window_seconds: int = Field(
        default=3600,
        alias="REGISTRATION_EMAIL_WINDOW_SECONDS"
    )

    registration_lock_seconds: int = Field(
        default=30,
        alias="REGISTRATION_LOCK_SECONDS"
    )

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
