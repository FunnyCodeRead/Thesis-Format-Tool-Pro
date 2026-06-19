import logging
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings

logger = logging.getLogger("thesis_api")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Thesis Format Tool Pro API",
        version="0.1.0",
        description="Backend API for safe Word document formatting.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "http_request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(api_router)

    return app


app = create_app()


@app.get("/", tags=["root"])
def read_root() -> dict[str, str]:
    return {
        "name": "Thesis Format Tool Pro API",
        "environment": settings.app_env,
        "status": "ok",
    }
