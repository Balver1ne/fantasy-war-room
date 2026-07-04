import logging


def configure_logging(level: str = "INFO") -> None:
    """Console logging tuned for the Phase-1 terminal deliverable.

    Draft events (PICK / RESYNC / STALE / RECOVERED) are logged by the sync loop
    through the ``warroom.draft`` logger and must stand out; everything else is
    quiet background noise.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", datefmt="%H:%M:%S")
    )
    root.handlers[:] = [handler]

    # uvicorn's access log would drown the pick feed while the SSE debug page polls
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


draft_log = logging.getLogger("warroom.draft")
