from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_API_KEY_LENGTH = 32
API_KEY_PLACEHOLDER = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://payments:payments@localhost:5432/payments"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # Нет значения по умолчанию: сервис обязан получить ключ из окружения.
    # Валидатор ниже отклоняет пустой ключ, плейсхолдер из .env.example и
    # ключи короче MIN_API_KEY_LENGTH символов.
    api_key: SecretStr

    # Interactive docs expose the full API surface without an API key, so they
    # are disabled by default. Enable them only for local development.
    enable_docs: bool = False

    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 100

    # SSRF-защита webhook. http разрешён только явным флагом (для локальных
    # e2e-стендов); список доверенных хостов по умолчанию пуст, то есть
    # адрес проверяется по результатам DNS-резолвинга.
    webhook_allow_http: bool = False
    webhook_allowed_hosts: str = ""

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()

        if not raw.strip():
            raise ValueError("API_KEY must not be empty")

        if raw.strip().lower() == API_KEY_PLACEHOLDER:
            raise ValueError(
                f"API_KEY must be changed from the {API_KEY_PLACEHOLDER!r} "
                "placeholder; generate one with "
                'python3 -c "import secrets; print(secrets.token_urlsafe(32))"',
            )

        if len(raw) < MIN_API_KEY_LENGTH:
            raise ValueError(
                f"API_KEY must be at least {MIN_API_KEY_LENGTH} characters long "
                f"(got {len(raw)})",
            )

        return value

    @property
    def webhook_allowed_host_names(self) -> frozenset[str]:
        """Нормализованный список доверенных хостов из ``WEBHOOK_ALLOWED_HOSTS``."""

        return frozenset(
            host.strip().lower().rstrip(".")
            for host in self.webhook_allowed_hosts.split(",")
            if host.strip()
        )


settings = Settings()
