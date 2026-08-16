import uvicorn

from warroom.app import create_app
from warroom.config import Settings
from warroom.log import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    # log_config=None keeps our root logging config instead of uvicorn's.
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port, log_config=None
    )


if __name__ == "__main__":
    main()
