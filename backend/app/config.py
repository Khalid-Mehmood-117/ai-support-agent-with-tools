"""Settings loaded from environment variables and the repo root .env file."""

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Relative paths are resolved from the backend folder.
    database_path: Path = Path("data/store.db")
    checkpoint_path: Path = Path("data/checkpoints.db")

    # The refund policy uses this date instead of the real clock, so results are reproducible.
    store_today: date = date(2026, 9, 15)
    max_tool_steps: int = 6

    cors_origins: str = "http://localhost:3000"

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
