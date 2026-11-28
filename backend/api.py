"""HTTP API over the ticket workflow."""

from __future__ import annotations

import base64
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

import config
import connections
import db
import intakes
import orchestrator
import parser
import selflooper
import solver
import verifier
from auth.deps import get_current_user, require_csrf
from auth.service import Product, User
from auth.sessions import cookie_secure, start_cleanup
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

FLEETAI = Product(id="fleetai", name="FleetAI", signup_tier="free")
TICKETS_FEATURE = "tickets"

_cleanup_stop = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _cleanup_stop
    db.open_pool()
    if db.pool is not None:
        selflooper.finish_pushing_runs("ok")
        _cleanup_stop = start_cleanup(intakes.purge_handled)
    yield
    if _cleanup_stop is not None:
        _cleanup_stop.set()
        _cleanup_stop = None
    db.close_pool()


app = FastAPI(title="fleetai", version=config.VERSION, lifespan=lifespan)
app.state.auth_product = FLEETAI


def require_tickets(user: User = Depends(get_current_user)) -> User:
    if TICKETS_FEATURE not in user.features:
        raise HTTPException(403, "forbidden")
    return user


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
    list_images_base64: list[Annotated[str, Field(max_length=7_000_000)]] = Field(default_factory=list, max_length=8)


class SettingsBody(BaseModel):
    ticket_retention_days: Literal[7, 30, 90] | None


class GithubReposBody(BaseModel):
    project: str = ""
    repos: list[str] = Field(default_factory=list, max_length=100)


class ExecuteBody(BaseModel):
    ticket_ids: list[str] = Field(default_factory=list, max_length=200)


class InstructionBody(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)


def _run_job(job: dict, user: User, call) -> None:
    try:
        with config.workflow_lock(user.id, blocking=False):
            with connections.github.checkout_for(user.id):
                call()
    except config.WorkflowBusy as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        return
    except (SystemExit, RuntimeError, Exception) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        return
    if job["ticket_id"]:
        job["run_id"] = intakes.latest_run_id(user.id, job["ticket_id"])
    job["status"] = "done"


def _run_improve(job: dict, user: User, instruction: str) -> None:
    try:
        with config.workflow_lock(user.id, blocking=False):
            project = selflooper.fleetai_project()
            if project["user_id"] != user.id:
                raise RuntimeError("FleetAI project is missing")
            selflooper.refuse_failed_run(project["id"])
            selflooper.run_instruction(user.id, project["id"], instruction)
    except config.WorkflowBusy as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        return
    except (SystemExit, RuntimeError, Exception) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        return
    job["status"] = "done"


def _start_job(kind: str, call, background: BackgroundTasks, user: User, ticket_id: str | None = None) -> dict:
    if config.workflow_busy(user.id):
        _busy()
    job = config.new_job(user.id, kind, ticket_id)
    background.add_task(_run_job, job, user, call)
    return dict(job)


@app.get("/health")
def health() -> dict:
    try:
        config.engineering_standard()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"status": "ok", "version": config.VERSION}


@app.get("/settings")
def get_settings(user: User = Depends(get_current_user)) -> dict:
    return {
        "subscription_status": user.subscription_status,
        "ticket_retention_days": intakes.keep_days(user.id),
        "editable": user.subscription_status == "paid",
    }


@app.put("/settings")
def put_settings(
    body: SettingsBody,
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf),
) -> dict:
    if user.subscription_status != "paid":
        raise HTTPException(403, "forbidden")
    intakes.set_keep_days(user.id, body.ticket_retention_days)
    return get_settings(user)


def _page(path: str, query: str = "") -> str:
    base = connections.github.redirect_uri().removesuffix("/api/v1/github/callback") if connections.github.configured() else ""
    return base + path + query


@app.get("/github")
def get_github(user: User = Depends(require_tickets)) -> dict:
    try:
        return connections.github.status(user.id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/github/repos")
def put_github_repos(
    body: GithubReposBody,
    user: User = Depends(require_tickets),
    _: None = Depends(require_csrf),
) -> dict:
    try:
        connections.github.save_repos(user.id, body.project, body.repos)
        return connections.github.status(user.id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/github", status_code=204, response_model=None)
def delete_github(user: User = Depends(require_tickets), _: None = Depends(require_csrf)) -> None:
    connections.github.disconnect(user.id)


@app.get("/github/connect")
def start_github_connect(user: User = Depends(require_tickets)) -> RedirectResponse:
    if not connections.github.configured():
        raise HTTPException(503, "GitHub is not configured")
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(connections.github.authorize_url(state), status_code=302)
    response.set_cookie(
        connections.github.STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        path="/",
        secure=cookie_secure(),
    )
    return response


@app.get("/github/callback")
def github_callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    def finish(response: RedirectResponse) -> RedirectResponse:
        response.delete_cookie(connections.github.STATE_COOKIE, path="/")
        return response

    failed = finish(RedirectResponse(_page("/connectors", "?github=failed"), status_code=302))
    if error or not code:
        return failed
    saved = request.cookies.get(connections.github.STATE_COOKIE) or ""
    if not saved or not secrets.compare_digest(saved, state):
        return failed
    try:
        user = get_current_user(request)
    except HTTPException:
        return finish(RedirectResponse(_page("/login"), status_code=302))
    if TICKETS_FEATURE not in user.features:
        raise HTTPException(403, "forbidden")
    try:
        token, login = connections.github.exchange_code(code)
        connections.github.save_connection(user.id, login, token)
    except RuntimeError:
        return failed
    return finish(RedirectResponse(_page("/connectors", "?github=connected"), status_code=302))


@app.get("/projects")
def get_projects(user: User = Depends(require_tickets)) -> list[dict]:
    return connections.list_projects(user.id)


@app.post("/self-improve", status_code=202)
def post_self_improve(
    body: InstructionBody,
    background: BackgroundTasks,
    user: User = Depends(require_tickets),
) -> dict:
    if user.user_type != "admin":
        raise HTTPException(403, "forbidden")
    text = body.instruction.strip()
    if not text:
        raise HTTPException(422, "invalid")
    if config.workflow_busy(user.id):
        _busy()
    db.remember("feedback", text)
    job = config.new_job(user.id, "improve")
    background.add_task(_run_improve, job, user, text)
    return dict(job)


@app.get("/tickets")
def get_tickets(project_id: UUID | None = None, user: User = Depends(require_tickets)) -> list[dict]:
    return intakes.list_visible_tickets(user.id, project_id)


@app.post("/tickets/inputs", status_code=204, response_model=None)
def post_inputs(body: IntakeBody, user: User = Depends(require_tickets)) -> None:
    pdf = None
    if body.list_pdf_base64:
        try:
            pdf = base64.b64decode(body.list_pdf_base64, validate=True)
        except Exception as exc:
            raise HTTPException(422, "invalid") from exc
    images = []
    for raw in body.list_images_base64:
        try:
            images.append(base64.b64decode(raw, validate=True))
        except Exception as exc:
            raise HTTPException(422, "invalid") from exc
    try:
        config.save_intake(body.email, body.list_text, body.context, pdf, user.id, user.session_id, images)
    except config.WorkflowBusy:
        _busy()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, user: User = Depends(require_tickets)) -> dict:
    ticket = intakes.find_ticket(user.id, ticket_id)
    if ticket is None:
        raise HTTPException(404, "ticket not found: {0}".format(ticket_id))
    return ticket


@app.get("/tickets/{ticket_id}/runs/{run_id}")
def get_run_log(ticket_id: str, run_id: str, user: User = Depends(require_tickets)) -> dict:
    text = config.read_run_log(user.id, ticket_id, run_id)
    if text is None:
        raise HTTPException(404, "run not found: {0} {1}".format(ticket_id, run_id))
    return {"ticket_id": ticket_id, "run_id": run_id, "text": text}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(require_tickets)) -> dict:
    job = config.load_job(user.id, job_id)
    if job is None:
        raise HTTPException(404, "job not found: {0}".format(job_id))
    return job


@app.post("/tickets/parse")
def parse_tickets(user: User = Depends(require_tickets)) -> list[dict]:
    try:
        with config.workflow_lock(user.id, blocking=False):
            return _call(parser.get_tickets, user.id, user.session_id)
    except config.WorkflowBusy:
        _busy()


@app.post("/tickets/{ticket_id}/solve", status_code=202)
def solve_ticket(ticket_id: str, background: BackgroundTasks, user: User = Depends(require_tickets)) -> dict:
    _call(config.require_ticket, user.id, ticket_id)
    return _start_job("solve", lambda: solver.solve(user.id, ticket_id), background, user, ticket_id)


@app.post("/tickets/{ticket_id}/verify", status_code=202)
def verify_ticket(ticket_id: str, background: BackgroundTasks, user: User = Depends(require_tickets)) -> dict:
    _call(config.require_ticket, user.id, ticket_id)
    return _start_job("verify", lambda: verifier.verify(user.id, ticket_id), background, user, ticket_id)


@app.post("/tickets/{ticket_id}/complete")
def complete_ticket(ticket_id: str, user: User = Depends(require_tickets)) -> dict:
    try:
        with config.workflow_lock(user.id, blocking=False):
            return _call(solver.complete, user.id, ticket_id)
    except config.WorkflowBusy:
        _busy()


@app.post("/execute", status_code=202)
def execute(
    background: BackgroundTasks,
    body: ExecuteBody | None = None,
    user: User = Depends(require_tickets),
) -> dict:
    ticket_ids = [item.strip() for item in (body.ticket_ids if body else []) if item and item.strip()]
    if not ticket_ids:
        raise HTTPException(400, "Select a ticket.")
    return _start_job(
        "execute",
        lambda: orchestrator.execute(user.id, user.session_id, ticket_ids),
        background,
        user,
    )
