from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from hesabdar.errors import AppError
from hesabdar.files.names import content_disposition, safe_echo_name
from hesabdar.files.service import RejectedFile, batch_failure
from hesabdar.messages import NO_FILES, ROUTE_NOT_FOUND, TOO_MANY_FILES, file_too_large

router = APIRouter(prefix="/api")


class WorkspaceIn(BaseModel):
    title: str


class InspectionIn(BaseModel):
    file_id: str


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/workspaces")
def workspace_index_is_not_public() -> None:
    raise AppError("route.not_found", ROUTE_NOT_FOUND, 404)


@router.post("/workspaces")
def create_workspace(body: WorkspaceIn, request: Request) -> JSONResponse:
    created = request.app.state.ctx.service.create_workspace(body.title)
    return JSONResponse(status_code=201, content=created)


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request) -> dict:
    return request.app.state.ctx.service.get_workspace(workspace_id)


@router.get("/workspaces/{workspace_id}/files")
def list_files(workspace_id: str, request: Request) -> dict:
    return {"files": request.app.state.ctx.service.list_files(workspace_id)}


@router.get("/workspaces/{workspace_id}/files/{file_id}")
def get_file(workspace_id: str, file_id: str, request: Request) -> dict:
    return request.app.state.ctx.service.get_file(workspace_id, file_id)


@router.post("/workspaces/{workspace_id}/files")
async def upload_files(
    workspace_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
) -> JSONResponse:
    ctx = request.app.state.ctx
    ctx.service.get_workspace(workspace_id)
    if not files:
        raise AppError("request.invalid", NO_FILES, 400)
    if len(files) > ctx.settings.max_files_per_upload:
        raise AppError(
            "file.too_many",
            TOO_MANY_FILES.format(limit=ctx.settings.max_files_per_upload),
            400,
        )
    payloads: list[tuple[str, bytes]] = []
    rejected: list[RejectedFile] = []
    for upload in files:
        name = upload.filename or ""
        try:
            data = await _read_limited(upload, ctx.settings.max_upload_bytes)
        except AppError as exc:
            rejected.append(
                RejectedFile(filename=safe_echo_name(name), code=exc.code, message=exc.message)
            )
            continue
        payloads.append((name, data))
    batch = ctx.service.store_files(workspace_id, payloads)
    batch.rejected = rejected + batch.rejected
    if not batch.accepted:
        raise batch_failure(batch)
    return JSONResponse(
        status_code=201,
        content={
            "accepted": [asdict(item) for item in batch.accepted],
            "rejected": [asdict(item) for item in batch.rejected],
        },
    )


@router.post("/workspaces/{workspace_id}/inspections")
def inspect_file(workspace_id: str, body: InspectionIn, request: Request) -> dict:
    return request.app.state.ctx.inspection.inspect(workspace_id, body.file_id)


@router.get("/workspaces/{workspace_id}/versions/{version_id}/download")
def download_version(workspace_id: str, version_id: str, request: Request) -> Response:
    meta, data = request.app.state.ctx.service.read_version(workspace_id, version_id)
    return Response(
        content=data,
        media_type=meta["media_type"],
        headers={
            "Content-Disposition": content_disposition(meta["original_name"]),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        piece = await upload.read(1024 * 1024)
        if not piece:
            break
        total += len(piece)
        if total > limit:
            raise AppError("file.too_large", file_too_large(limit), 413)
        chunks.append(piece)
    return b"".join(chunks)
