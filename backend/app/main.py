from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import SAFE_METHODS
from app.api.routes import (
    ai,
    applications,
    portal_intake,
    audit,
    auth,
    evidence,
    extraction,
    insights,
    review,
    rules,
    system,
    trust,
    users,
    validation,
)
from app.core.config import get_settings
from app.core.errors import error_body, install_error_handlers
from app.core.logging import configure_logging, request_id_var

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

access_log = logging.getLogger("verifyflow.access")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        docs_url="/api/docs" if settings.api_docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
    )
    install_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "X-Session-Expires"],
    )

    allowed_origins = set(settings.cors_origins)

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):  # noqa: ANN001, ANN202
        """Second CSRF layer: browsers send Origin on cross-site state-changing requests.

        Reject unsafe requests whose Origin is neither this server nor an allowed frontend.
        This also covers unauthenticated endpoints such as login (login CSRF).
        """
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            same_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin is not None and origin != same_origin and origin not in allowed_origins:
                logging.getLogger("verifyflow.security").warning(
                    "Rejected %s %s from disallowed origin %s", request.method, request.url.path, origin
                )
                return JSONResponse(
                    status_code=403, content=error_body("origin_rejected", "Request origin is not allowed")
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001, ANN202
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers.setdefault("Cache-Control", "no-store")
            expires = getattr(request.state, "session_expires", None)
            if expires:
                response.headers["X-Session-Expires"] = expires
            return response
        finally:
            # Path only: query strings may carry sensitive values.
            access_log.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                status,
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "client": request.client.host if request.client else None,
                    }
                },
            )
            request_id_var.reset(token)

    routers = (
        system, auth, users, audit, applications, portal_intake, extraction, evidence, rules, validation, review, trust, ai, insights,
    )
    for r in (m.router for m in routers):
        app.include_router(r, prefix=settings.api_prefix)
    return app


app = create_app()
