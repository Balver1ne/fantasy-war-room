from warroom.config import Settings
from warroom.platforms.base import PlatformAdapter


def get_adapter(platform: str, settings: Settings) -> PlatformAdapter:
    if platform == "sleeper":
        from warroom.platforms.sleeper.adapter import SleeperAdapter

        return SleeperAdapter(settings)
    raise ValueError(f"Unknown platform: {platform!r}")
