import logging
import os

from core.request_context import install_log_record_factory

# Single source of truth for log formatting so EVERY log line is timestamped and carries
# request correlation — our app logs, uvicorn's startup/access/error logs, and any library
# logs. request_id/profile_id are injected onto every record by the log-record factory
# (core.request_context), so these fields are always present (default "-").
_FORMATTER = logging.Formatter(
    "%(asctime)s.%(msecs)03d [%(levelname)s] [%(threadName)s] "
    "[req:%(request_id)s p:%(profile_id)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def configure_logging(level=None):
    """Apply the timestamped formatter to the root logger and uvicorn's loggers.

    Idempotent and safe to call from multiple modules. Under the CLI launcher,
    uvicorn configures its logging first and imports the app afterwards, so
    reformatting uvicorn's handlers here takes effect. The level defaults to the
    LOG_LEVEL env var (else INFO); pass `level` to override."""
    if level is None:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    install_log_record_factory()

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

    # Silence uvicorn's own access log: it's emitted from the protocol layer *after* our
    # request-context middleware has reset the contextvars, so it can't carry req/profile
    # and would just duplicate (uncorrelated) the access line the middleware already logs.
    # Disabling the logger here is launcher-independent (survives --reload, any uvicorn
    # invocation); uvicorn.error (startup/reload notices) is untouched.
    logging.getLogger("uvicorn.access").disabled = True
