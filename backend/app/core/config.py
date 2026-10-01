from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://albiruni:albiruni@localhost:5432/albiruni_erp"
    # Apply database migrations when the API starts. Turn off where deploys run `alembic upgrade head`.
    auto_migrate: bool = True
    jwt_secret: str = "dev-only-secret-do-not-use-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:5173"
    # Where uploaded files are kept (one folder per tenant). Relative paths
    # are relative to the directory the API is started from.
    attachments_dir: str = "var/attachments"
    attachment_max_mb: int = 10
    # Notification emails. Without SMTP_HOST they stay in-app only.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    # Links in emails point here (the web app).
    app_url: str = "http://localhost:5173"
    # Background worker: overdue follow-up alerts and email sending.
    notification_worker: bool = True
    notification_interval_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
