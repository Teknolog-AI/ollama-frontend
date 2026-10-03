from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


def canonical_model(name: str) -> str:
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    ollama_base_url: str = "http://127.0.0.1:11434"
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    github_token: SecretStr | None = None
    allowed_models: list[str] = Field(
        default_factory=lambda: ["qwen3.5:4b-q4_K_M", "gurkan-ai"], min_length=1
    )
    cors_origins: list[str] = Field(default_factory=list)
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)
    github_timeout_seconds: float = Field(default=15, gt=0, le=60)
    model_list_timeout_seconds: float = Field(default=10, gt=0, le=60)
    chat_timeout_seconds: float = Field(default=180, gt=0, le=900)
    max_tool_rounds: int = Field(default=3, ge=1, le=5)
    max_tool_calls: int = Field(default=10, ge=1, le=20)

    @field_validator("ollama_base_url", "github_api_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Geçerli bir HTTP(S) adresi gerekli")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Adres kullanıcı bilgisi veya sorgu içeremez")
        return value

    @field_validator("allowed_models")
    @classmethod
    def validate_models(cls, values: list[str]) -> list[str]:
        names = list(dict.fromkeys(value.strip() for value in values))
        if any(not name or len(name) > 128 for name in names):
            raise ValueError("Model adları boş olamaz ve 128 karakteri aşamaz")
        return names
