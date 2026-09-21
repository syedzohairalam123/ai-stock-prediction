"""
Phase 11/12 — server persistence for the workspace and chart workspace.

The frontend storage adapters (`lib/workspace/storage.ts`,
`lib/charting/...`) already speak this contract; these routes are what
`createBackendStorage()` was prepared to call. Documents are stored as JSON in
the generic `workspace_blobs` table, so no new table is needed per document
kind.

Endpoints
    GET  /api/workspace/layouts     active per-preset layouts  -> object
    PUT  /api/workspace/layouts     save active layouts        <- object
    GET  /api/workspace/saved       saved custom workspaces    -> array
    PUT  /api/workspace/saved       save custom workspaces     <- array
    GET  /api/chart-workspace       chart workspace document   -> object
    PUT  /api/chart-workspace       save chart workspace       <- object

Nothing here validates the *shape* of a layout beyond "it is JSON": the client
already owns that schema, and rejecting a slightly-older payload would lose a
user's layout. The storage is versioned by the client.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from . import repository as repo
from .logging_config import get_logger

logger = get_logger("neural_market.workspace")

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])
chart_router = APIRouter(prefix="/api/chart-workspace", tags=["Chart Workspace"])

LAYOUTS_KEY = "workspace:layouts"
SAVED_KEY = "workspace:saved"
CHART_KEY = "chart:workspace"


@router.get("/layouts")
def get_layouts() -> Any:
    record = repo.get_blob(LAYOUTS_KEY)
    if record is None:
        # `null` is the contract's "nothing stored yet" signal.
        return JSONResponse(content=None)
    return record.get("payload") or {}


@router.put("/layouts")
def put_layouts(payload: dict[str, Any] = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(400, "Layouts must be a JSON object keyed by preset id.")
    try:
        repo.put_blob(LAYOUTS_KEY, payload)
    except Exception as exc:
        logger.error("failed to persist layouts: %s", exc)
        raise HTTPException(500, "Could not save the workspace layout.")
    return {"saved": True, "presets": list(payload.keys())}


@router.get("/saved")
def get_saved_workspaces() -> Any:
    record = repo.get_blob(SAVED_KEY)
    if record is None:
        return []
    payload = record.get("payload") or {}
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


@router.put("/saved")
def put_saved_workspaces(payload: list[dict[str, Any]] = Body(...)):
    if not isinstance(payload, list):
        raise HTTPException(400, "Saved workspaces must be a JSON array.")
    try:
        repo.put_blob(SAVED_KEY, {"items": payload})
    except Exception as exc:
        logger.error("failed to persist saved workspaces: %s", exc)
        raise HTTPException(500, "Could not save the workspace.")
    return {"saved": True, "count": len(payload)}


@chart_router.get("")
def get_chart_workspace() -> Any:
    record = repo.get_blob(CHART_KEY)
    if record is None:
        return JSONResponse(content=None)
    return record.get("payload") or {}


@chart_router.put("")
def put_chart_workspace(payload: dict[str, Any] = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(400, "Chart workspace must be a JSON object.")
    try:
        repo.put_blob(CHART_KEY, payload)
    except Exception as exc:
        logger.error("failed to persist chart workspace: %s", exc)
        raise HTTPException(500, "Could not save the chart workspace.")
    return {"saved": True}
