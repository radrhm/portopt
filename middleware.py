"""Flask middleware — request IDs and request/response logging."""

import logging
import time
import uuid

from flask import Flask, g, request

logger = logging.getLogger(__name__)


def register_middleware(app: Flask) -> None:
    """Attach request-ID assignment and request logging to *app*."""

    @app.before_request
    def _before_request():
        g.request_id = (
            request.headers.get("X-Request-ID")
            or uuid.uuid4().hex[:12]
        )
        g.start_ts = time.monotonic()

    @app.after_request
    def _after_request(resp):
        dur_ms = -1
        try:
            dur_ms = int((time.monotonic() - g.start_ts) * 1000)
        except (AttributeError, TypeError):
            pass
        rid = getattr(g, "request_id", "-")
        logger.info(
            "req=%s %s %s -> %s in %dms",
            rid, request.method, request.path, resp.status_code, dur_ms,
        )
        resp.headers["X-Request-ID"] = rid
        return resp
