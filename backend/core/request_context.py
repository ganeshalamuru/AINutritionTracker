"""Per-request log correlation: a request id (trace id) and the calling profile id,
carried in contextvars and stamped onto every log record.

The HTTP middleware (main.py) binds these per request; a log-record factory copies
them onto each LogRecord so the formatter's %(request_id)s / %(profile_id)s fields are
always present — even for startup, uvicorn, and third-party logs emitted with no request
in flight (those render the "-" default). contextvars (not thread-locals) so the values
survive across asyncio.to_thread, and copy_context() can carry them into the USDA
ThreadPoolExecutor workers."""

import contextvars
import logging
import uuid

# "-" reads cleanly in the log when no request is in flight (startup, uvicorn).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
profile_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("profile_id", default="-")


def new_request_id() -> str:
    """A short trace id — 8 hex chars is plenty to disambiguate concurrent requests."""
    return uuid.uuid4().hex[:8]


_factory_installed = False


def install_log_record_factory() -> None:
    """Wrap the active LogRecord factory so every record carries request_id/profile_id.

    Idempotent: configure_logging() may run more than once, but we only wrap once so the
    chain doesn't grow."""
    global _factory_installed
    if _factory_installed:
        return
    base_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base_factory(*args, **kwargs)
        record.request_id = request_id_var.get()
        record.profile_id = profile_id_var.get()
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True
