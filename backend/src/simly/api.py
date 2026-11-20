"""HTTP API for the web app.

    GET  /api/health      what is installed (solver, mesher, AI provider)
    GET  /api/templates   templates, materials and JSON schemas for the forms
    POST /api/plan        plain-language request -> validated study spec (AI)
    POST /api/parts       upload an STL/STEP part -> faces for picking
    GET  /api/parts/{id}  faces again, e.g. in other units
    POST /api/simulate    study spec -> results (optionally with a GCI mesh study)
    POST /api/explain     results -> classroom explanation (AI)

If a built frontend exists (frontend/dist), it is served at /.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import __version__
from .ai import Declined, NoValidSpec, explain_results, plan_study
from .convergence import run_convergence
from .geometry import MeshError
from .llm import LLMError, make_client
from .materials import MATERIALS
from .parts import UNIT_SCALE, PartError, describe_part, save_upload
from .solver import SolverError
from .spec import TEMPLATES, parse_spec
from .study import run_study

RUNS_DIR = Path(os.environ.get("SIMLY_RUNS", Path(tempfile.gettempdir()) / "simly-runs"))
FRONTEND_DIST = Path(
    os.environ.get("SIMLY_FRONTEND", Path(__file__).resolve().parents[3] / "frontend" / "dist")
)

# Public-deployment guard rails: limited simultaneous solver jobs, and a per-IP
# hourly budget for AI calls (they cost money).
MAX_JOBS = int(os.environ.get("SIMLY_MAX_JOBS", "2"))
AI_PER_HOUR = int(os.environ.get("SIMLY_AI_PER_HOUR", "30"))
_jobs = threading.BoundedSemaphore(MAX_JOBS)
_ai_calls: dict[str, deque] = defaultdict(deque)
_ai_lock = threading.Lock()

app = FastAPI(title="Simly", version=__version__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _ai_budget(request: Request) -> None:
    now, ip = time.time(), _client_ip(request)
    with _ai_lock:
        calls = _ai_calls[ip]
        while calls and now - calls[0] > 3600:
            calls.popleft()
        if len(calls) >= AI_PER_HOUR:
            raise HTTPException(429, {"error": "AI request limit reached; try again later, "
                                      "or set up the study by hand."})
        calls.append(now)


class PlanRequest(BaseModel):
    prompt: str


class SimulateRequest(BaseModel):
    spec: dict[str, Any]
    convergence: bool = False


class ExplainRequest(BaseModel):
    prompt: str = ""
    result: dict[str, Any]


def _client():
    try:
        return make_client()
    except LLMError as e:
        raise HTTPException(503, str(e)) from e


@app.get("/api/health")
def health() -> dict:
    try:
        import gmsh  # noqa: F401

        has_gmsh = True
    except ImportError:
        has_gmsh = False
    provider = next(
        (p for p, k in [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")]
         if os.environ.get(k)),
        None,
    )
    return {
        "version": __version__,
        "solver": shutil.which("ccx") is not None,
        "mesher": has_gmsh,
        "ai_provider": os.environ.get("SIMLY_PROVIDER", provider),
    }


@app.get("/api/templates")
def templates() -> dict:
    return {
        "templates": {
            name: {"description": model.__doc__.strip(), "schema": model.model_json_schema()}
            for name, model in TEMPLATES.items()
        },
        "materials": {k: m.model_dump() for k, m in MATERIALS.items()},
    }


@app.get("/api/materials")
def materials() -> dict:
    return {
        k: {**m.model_dump(), "design_strength": m.design_strength,
            "weakest_strength": m.weakest_strength}
        for k, m in MATERIALS.items()
    }


@app.post("/api/plan")
def plan(req: PlanRequest, request: Request) -> dict:
    if len(req.prompt) > 2000:
        raise HTTPException(422, {"error": "Please keep the description under 2000 characters."})
    _ai_budget(request)
    try:
        result = plan_study(req.prompt, _client())
    except Declined as e:
        raise HTTPException(422, {"declined": e.reason, "closest": e.closest}) from e
    except (NoValidSpec, LLMError) as e:
        raise HTTPException(422, {"error": str(e)}) from e
    return {"spec": result.spec.model_dump(mode="json"), "attempts": result.attempts}


@app.post("/api/parts")
async def upload_part(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency idiom
    units: str = Form("mm"),
) -> dict:
    if units not in UNIT_SCALE:
        raise HTTPException(422, {"error": f"units must be one of {list(UNIT_SCALE)}"})
    data = await file.read()
    try:
        part_id = save_upload(data, file.filename or "")
        return describe_part(part_id, units)
    except PartError as e:
        raise HTTPException(422, {"error": str(e)}) from e


@app.get("/api/parts/{part_id}")
def get_part(part_id: str, units: str = "mm") -> dict:
    if units not in UNIT_SCALE:
        raise HTTPException(422, {"error": f"units must be one of {list(UNIT_SCALE)}"})
    try:
        return describe_part(part_id, units)
    except PartError as e:
        raise HTTPException(404, {"error": str(e)}) from e


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    try:
        spec = parse_spec(req.spec)
    except ValidationError as e:
        raise HTTPException(422, {"errors": [
            {"field": ".".join(map(str, err["loc"])), "message": err["msg"]}
            for err in e.errors()
        ]}) from e
    if not _jobs.acquire(timeout=30):
        raise HTTPException(503, {"error": "The server is busy with other simulations; "
                                  "try again in a moment."})
    work = RUNS_DIR / uuid.uuid4().hex[:12]
    try:
        if req.convergence:
            return run_convergence(spec, work).to_dict()
        return run_study(spec, work).to_dict()
    except (MeshError, PartError) as e:
        raise HTTPException(422, {"error": str(e)}) from e
    except SolverError as e:
        raise HTTPException(500, {"error": str(e)}) from e
    finally:
        _jobs.release()
        if not os.environ.get("SIMLY_KEEP_RUNS"):
            shutil.rmtree(work, ignore_errors=True)


@app.post("/api/explain")
def explain(req: ExplainRequest, request: Request) -> dict:
    _ai_budget(request)
    try:
        return {"explanation": explain_results(req.prompt, req.result, _client())}
    except (LLMError, KeyError) as e:
        raise HTTPException(422, {"error": str(e)}) from e


if FRONTEND_DIST.is_dir():  # pragma: no cover - depends on a built frontend
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "favicon.svg", media_type="image/svg+xml")
