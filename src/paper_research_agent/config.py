"""Load and validate configuration without starting services or making API calls."""

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    """Application settings; secrets are masked in model representations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-4.1-mini", min_length=1)
    openai_base_url: str = "https://api.openai.com/v1"
    openai_token_parameter: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    arxiv_max_results: int = Field(default=5, ge=1, le=20)
    pdf_max_pages: int = Field(default=50, ge=1)
    pdf_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    pdf_max_text_chars: int = Field(default=500_000, ge=1)
    request_timeout_seconds: float = Field(default=60, gt=0)
    agent_max_tool_rounds: int = Field(default=8, ge=1, le=50)
    agent_tool_timeout_seconds: float = Field(default=90, gt=0)
    agent_task_timeout_seconds: float = Field(default=300, gt=0)
    agent_max_result_chars: int = Field(default=16000, ge=1000, le=100000)
    agent_max_task_result_chars: int = Field(default=64000, ge=1000, le=500000)
    agent_max_repeated_calls: int = Field(default=2, ge=1, le=10)
    agent_max_calls_per_round: int = Field(default=4, ge=1, le=20)
    agent_max_llm_calls: int = Field(default=40, ge=1, le=100)
    agent_token_budget: int = Field(default=320000, ge=1000)
    agent_context_budget: int = Field(default=64000, ge=1000)
    agent_output_tokens: int = Field(default=3000, ge=100, le=10000)
    analysis_output_tokens: int = Field(default=6000, ge=100, le=10000)
    analysis_chunk_bytes: int = Field(default=12000, ge=256, le=30000)
    analysis_max_chunks: int = Field(default=24, ge=1, le=100)
    analysis_format_retries: int = Field(default=1, ge=0, le=2)
    data_dir: Path = PROJECT_ROOT / "data"

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_key(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("openai_model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("OPENAI_BASE_URL must be an HTTPS API base URL")
        parts = urlsplit(value.strip())
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Use an HTTPS API URL without credentials, query or fragment")
        path = parts.path.rstrip("/")
        if path.endswith("/chat/completions"):
            path = path[:-len("/chat/completions")]
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    @field_validator("data_dir", mode="before")
    @classmethod
    def resolve_data_dir(cls, value: str | Path) -> Path:
        if isinstance(value, str) and not value.strip():
            raise ValueError("DATA_DIR must not be empty")
        path = Path(value).expanduser()
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    def require_openai_api_key(self) -> str:
        """Check the key only when a later stage actually needs the LLM."""
        if self.openai_api_key is None:
            raise ValueError("请在项目 .env 或环境变量中设置 OPENAI_API_KEY。")
        return self.openai_api_key.get_secret_value()


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Read .env then override with process environment; do not mutate os.environ.

    Unrelated environment variables are ignored. No directories are created.
    """
    file_values = dotenv_values(
        Path(env_file) if env_file is not None else PROJECT_ROOT / ".env",
        interpolate=False,
    )
    values = {}
    for field_name in Settings.model_fields:
        env_name = field_name.upper()
        value = os.environ.get(env_name, file_values.get(env_name))
        if value is not None:
            values[field_name] = value
    return Settings(**values)
