import logging

# Single source of truth for log formatting so EVERY log line is timestamped —
# our app logs, uvicorn's startup/access/error logs, and any library logs.
_FORMATTER = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def configure_logging(level=logging.INFO):
    """Apply the timestamped formatter to the root logger and uvicorn's loggers.

    Idempotent and safe to call from multiple modules. Under the CLI launcher,
    uvicorn configures its logging first and imports the app afterwards, so
    reformatting uvicorn's handlers here takes effect."""
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(_FORMATTER)
    root.setLevel(level)

    # uvicorn keeps dedicated loggers with their own handlers — reformat those too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(_FORMATTER)
