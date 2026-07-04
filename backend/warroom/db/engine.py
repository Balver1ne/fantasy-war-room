from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from warroom.db.models import Base


def make_engine(db_path: Path | str) -> Engine:
    """Synchronous SQLite engine, safe to call from async code.

    Writes at Phase-1 volumes are sub-millisecond; if profiling ever shows event-loop
    stalls, wrap the hot calls in asyncio.to_thread rather than switching to aiosqlite.
    """
    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path.as_posix()}"
    else:
        url = db_path  # e.g. "sqlite://" in-memory for tests
    return create_engine(url, connect_args={"check_same_thread": False})


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    # create_all is the Phase-1 migration story: every table mirrors Sleeper truth,
    # so schema changes are handled by deleting warroom.db and resyncing (see CLAUDE.md).
    Base.metadata.create_all(engine)
