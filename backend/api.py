"""HTTP API over the existing ticket workflow."""

from __future__ import annotations

from contextlib import asynccontextmanager

import config
import db
import orchestrator
import parser
import solver
import verifier
from auth.routes import router as auth_router
from auth.sessions import start_cleanup
from fastapi import BackgroundTasks, FastAPI, HTTPException

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
    config.save_job(job)


def _start_job(kind: str, fn, background: BackgroundTasks, ticket_id: str | None = None) -> dict:
    if config.workflow_busy():
        _busy()
    job = config.new_job(kind, ticket_id)
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
def get_tickets() -> list[dict]:
    return config.load_tickets()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    ticket = config.find_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(404, "ticket not found: {0}".format(ticket_id))
    return ticket


@app.get("/tickets/{ticket_id}/runs/{run_id}")
def get_run_log(ticket_id: str, run_id: str) -> dict:
    text = config.read_run_log(ticket_id, run_id)
    if text is None:
        raise HTTPException(404, "run not found: {0} {1}".format(ticket_id, run_id))
    return {"ticket_id": ticket_id, "run_id": run_id, "text": text}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = config.load_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found: {0}".format(job_id))
    return job


@app.post("/tickets/parse")
def parse_tickets() -> list[dict]:
    try:
        with config.workflow_lock(blocking=False):
            return _call(parser.get_tickets)
    except config.WorkflowBusy:
        _busy()


@app.post("/tickets/{ticket_id}/solve", status_code=202)
def solve_ticket(ticket_id: str, background: BackgroundTasks) -> dict:
    _call(config.require_ticket, ticket_id)
    return _start_job("solve", solver.solve, background, ticket_id)


@app.post("/tickets/{ticket_id}/verify", status_code=202)
def verify_ticket(ticket_id: str, background: BackgroundTasks) -> dict:
    _call(config.require_ticket, ticket_id)
    return _start_job("verify", verifier.verify, background, ticket_id)


@app.post("/tickets/{ticket_id}/complete")
def complete_ticket(ticket_id: str) -> dict:
    try:
        with config.workflow_lock(blocking=False):
            _call(solver.complete, ticket_id)
            ticket = config.find_ticket(ticket_id)
    except config.WorkflowBusy:
        _busy()
    if ticket is None:
        raise HTTPException(404, "ticket not found: {0}".format(ticket_id))
    return ticket


@app.post("/execute", status_code=202)
def execute(background: BackgroundTasks) -> dict:
    return _start_job("execute", orchestrator.execute, background)
