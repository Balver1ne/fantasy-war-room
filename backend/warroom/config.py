from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WARROOM_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8734
    db_path: Path = Path("data/warroom.db")
    season: str = "2026"
    poll_interval: float = 2.0
    traded_picks_interval: float = 60.0
    max_backoff: float = 10.0
    player_sync_max_age_hours: int = 24
    sleeper_base_url: str = "https://api.sleeper.app/v1"
    log_level: str = "INFO"
