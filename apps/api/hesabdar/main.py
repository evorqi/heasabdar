from __future__ import annotations

import logging

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from hesabdar.api.routes import router
from hesabdar.config import Settings, ensure_network_is_locked
from hesabdar.context import AppContext
from hesabdar.db import Database
from hesabdar.errors import AppError, UnsafeBind
from hesabdar.files.service import FileService
from hesabdar.files.storage import Storage
from hesabdar.messages import INTERNAL, REQUEST_INVALID, ROUTE_NOT_FOUND, UNSAFE_BIND
from hesabdar.security.access import authorize

logger = logging.getLogger("hesabdar")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    ensure_network_is_locked(settings)
    settings.data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    database = Database(settings.data_dir / "hesabdar.sqlite")
    storage = Storage(settings.data_dir, tmp_max_age_seconds=settings.tmp_max_age_seconds)
    storage.cleanup_old_tmp()
    service = FileService(
        db=database,
        storage=storage,
        max_uncompressed_bytes=settings.max_uncompressed_bytes,
        max_files_per_upload=settings.max_files_per_upload,
        max_upload_bytes=settings.max_upload_bytes,
    )
    app = FastAPI(title="hesabdar", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.ctx = AppContext(settings=settings, db=database, storage=storage, service=service)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router, dependencies=[Depends(authorize)])
    _install_handlers(app)
    return app


def _install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_payload(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"code": "request.invalid", "message": REQUEST_INVALID, "detail": None},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={"code": "route.not_found", "message": ROUTE_NOT_FOUND, "detail": None},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": "request.invalid", "message": REQUEST_INVALID, "detail": None},
        )

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=500,
            content={"code": "internal", "message": INTERNAL, "detail": None},
        )


def _payload(exc: AppError) -> dict:
    return {"code": exc.code, "message": exc.message, "detail": exc.detail}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        settings = Settings.from_env()
        app = create_app(settings)
    except UnsafeBind:
        raise SystemExit(UNSAFE_BIND) from None
    uvicorn.run(app, host=settings.host, port=settings.port)
