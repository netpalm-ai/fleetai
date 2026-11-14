"""HTTP API over the existing ticket workflow."""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from uuid import UUID

import config
import db
import intakes
import orchestrator
import parser
import solver
import verifier
from auth.deps import require_tickets
from auth.routes import router as auth_router
from auth.service import User
from auth.sessions import start_cleanup
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

_cleanup_stop = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _cleanup_stop
    db.open_pool()
    if db.pool is not None:
        _cleanup_stop = start_cleanup()
    yield
    if _cleanup_stop is not None:
        _cleanup_stop.set()
        _cleanup_stop = None
    db.close_pool()


app = FastAPI(title="fleetai", version=config.VERSION, lifespan=lifespan)
app.include_router(auth_router, prefix="/auth")


def _call(fn, *args):
    try:
        return fn(*args)
    except SystemExit as exc:
        message = str(exc)
        status = 404 if "not found" in message else 409
        raise HTTPException(status, message) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


def _busy() -> None:
    raise HTTPException(409, "workflow busy")


class IntakeBody(BaseModel):
    email: str = Field(default="", max_length=524288)
    list_text: str = Field(default="", max_length=524288)
    context: str = Field(default="", max_length=524288)
    list_pdf_base64: str | None = Field(default=None, max_length=70_000_000)


def _sync_tickets(user: User) -> None:
    intakes.sync_tickets(user.id, user.session_id, config.load_tickets())


def _sync_job_tickets(job: dict) -> None:
    raw = job.get("user_id")
    if not raw:
        return
    session_raw = job.get("session_id")
    intakes.sync_tickets(
        UUID(str(raw)),
        UUID(str(session_raw)) if session_raw else None,
        config.load_tickets(),
    )


def _run_job(job_id: str, fn, ticket_id: str | None) -> None:
    job = config.load_job(job_id)
    if job is None:
        return
    try:
        with config.workflow_lock(blocking=False):
            fn() if ticket_id is None else fn(ticket_id)
    except config.WorkflowBusy as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        config.save_job(job)
        return
    except (SystemExit, RuntimeError, Exception) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        config.save_job(job)
        return
    job["status"] = "done"
    if ticket_id:
        ticket = config.find_ticket(ticket_id)
        job["ticket"] = ticket
        job["run_id"] = (ticket or {}).get("solver_run_id")
    else:
        job["tickets"] = config.load_tickets()
    _sync_job_tickets(job)
    config.save_job(job)


def _start_job(kind: str, fn, background: BackgroundTasks, user: User, ticket_id: str | None = None) -> dict:
    if config.workflow_busy():
        _busy()
    job = config.new_job(kind, ticket_id)
    job["user_id"] = str(user.id)
    job["session_id"] = str(user.session_id) if user.session_id else None
    config.save_job(job)
    background.add_task(_run_job, job["id"], fn, ticket_id)
    return job


@app.get("/health")
def health() -> dict:
    try:
        config.engineering_standard()
        config.code_context()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"status": "ok", "version": config.VERSION}


@app.get("/tickets")
def get_tickets(_user: User = Depends(require_tickets)) -> list[dict]:
    tracked = intakes.list_open_tickets(_user.id)
    if tracked is not None:
        return tracked
    return config.load_tickets()


@app.post("/tickets/inputs", status_code=204, response_model=None)
def post_inputs(body: IntakeBody, user: User = Depends(require_tickets)) -> None:
    pdf = None
    if body.list_pdf_base64:
        try:
            pdf = base64.b64decode(body.list_pdf_base64, validate=True)
        except Exception as exc:
            raise HTTPException(422, "invalid") from exc
    try:
        config.save_intake(body.email, body.list_text, body.context, pdf, user.id, user.session_id)
    except config.WorkflowBusy:
        _busy()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, _user: User = Depends(require_tickets)) -> dict:
    ticket = config.find_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(404, "ticket not found: {0}".format(ticket_id))
    return ticket


@app.get("/tickets/{ticket_id}/runs/{run_id}")
def get_run_log(ticket_id: str, run_id: str, _user: User = Depends(require_tickets)) -> dict:
    text = config.read_run_log(ticket_id, run_id)
    if text is None:
        raise HTTPException(404, "run not found: {0} {1}".format(ticket_id, run_id))
    return {"ticket_id": ticket_id, "run_id": run_id, "text": text}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, _user: User = Depends(require_tickets)) -> dict:
    job = config.load_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found: {0}".format(job_id))
    return job


@app.post("/tickets/parse")
def parse_tickets(user: User = Depends(require_tickets)) -> list[dict]:
    try:
        with config.workflow_lock(blocking=False):
            tickets = _call(parser.get_tickets)
            intakes.sync_tickets(user.id, user.session_id, tickets)
            return tickets
    except config.WorkflowBusy:
        _busy()


@app.post("/tickets/{ticket_id}/solve", status_code=202)
def solve_ticket(ticket_id: str, background: BackgroundTasks, user: User = Depends(require_tickets)) -> dict:
    _call(config.require_ticket, ticket_id)
    return _start_job("solve", solver.solve, background, user, ticket_id)


@app.post("/tickets/{ticket_id}/verify", status_code=202)
def verify_ticket(ticket_id: str, background: BackgroundTasks, user: User = Depends(require_tickets)) -> dict:
    _call(config.require_ticket, ticket_id)
    return _start_job("verify", verifier.verify, background, user, ticket_id)


@app.post("/tickets/{ticket_id}/complete")
def complete_ticket(ticket_id: str, user: User = Depends(require_tickets)) -> dict:
    try:
        with config.workflow_lock(blocking=False):
            _call(solver.complete, ticket_id)
            ticket = config.find_ticket(ticket_id)
            _sync_tickets(user)
    except config.WorkflowBusy:
        _busy()
    if ticket is None:
        raise HTTPException(404, "ticket not found: {0}".format(ticket_id))
    return ticket


@app.post("/execute", status_code=202)
def execute(background: BackgroundTasks, user: User = Depends(require_tickets)) -> dict:
    return _start_job("execute", orchestrator.execute, background, user)
