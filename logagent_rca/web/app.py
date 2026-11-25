"""FastAPI web adapter for LogAgent-RCA.

This module contains no RCA logic: every operation calls ``AppService`` (shared with the CLI), which runs the
existing engine (``runner.run_one``). Long analyses run on a single background worker; HTTP requests only enqueue.
"""
from __future__ import annotations

import contextlib
import ipaddress
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..report_render import build_view, to_markdown
from ..service import AnalysisRefused, AppService, ValidationProblem
from .auth import LOCAL_HEADER, SESSION_COOKIE, SESSION_TTL_S, Auth, User
from .jobs import JobWorker

HERE = Path(__file__).resolve().parent
LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]", "::1", "testserver"]


class AnalyzeRequest(BaseModel):
    mode: Literal["E2b", "E3"]


class ErrorBody(BaseModel):
    detail: str
    errors: dict[str, str] = {}


def is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def create_app(service: AppService, auth: Optional[Auth] = None, start_worker: bool = True,
               allowed_hosts: Optional[list[str]] = None) -> FastAPI:
    auth = auth or Auth()
    worker = JobWorker(service)
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="LogAgent-RCA", version="0.2.0", docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.service, app.state.auth, app.state.worker = service, auth, worker
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or LOOPBACK_HOSTS)
    max_body = service.limits.max_total_bytes + 2_000_000

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > max_body:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self'; "
                                                   "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ identity
    def current(request: Request) -> tuple[Optional[User], Optional[str]]:
        if auth.mode == "local":
            return User("local", "admin"), None
        got = auth.session(request.cookies.get(SESSION_COOKIE))
        return got if got else (None, None)

    def user_api(request: Request) -> User:
        user, _ = current(request)
        if user is None:
            raise HTTPException(401, "login required")
        return user

    def writer(request: Request) -> User:
        user, csrf = current(request)
        if user is None:
            raise HTTPException(401, "login required")
        if auth.mode == "local":
            if request.headers.get(LOCAL_HEADER[0]) != LOCAL_HEADER[1]:
                raise HTTPException(403, "missing anti-CSRF header")
        elif not csrf or request.headers.get("X-CSRF-Token") != csrf:
            raise HTTPException(403, "invalid CSRF token")
        if not user.can("write"):
            raise HTTPException(403, "your role cannot create or analyse investigations")
        return user

    def owner_filter(user: User) -> Optional[str]:
        return None if user.can("read_all") else user.username

    def load_owned(inv_id: str, user: User):
        try:
            inv = service.store.load(inv_id)
        except KeyError:
            raise HTTPException(404, "investigation not found")
        if not user.can("read_all") and inv.owner != user.username:
            raise HTTPException(404, "investigation not found")          # do not reveal existence
        return inv

    @app.exception_handler(ValidationProblem)
    async def _vp(request: Request, exc: ValidationProblem):
        return JSONResponse(ErrorBody(detail="validation failed", errors=exc.errors).model_dump(), status_code=422)

    @app.exception_handler(AnalysisRefused)
    async def _ar(request: Request, exc: AnalysisRefused):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # ------------------------------------------------------------------ API: system
    @app.get("/api/health")
    def health(user: User = Depends(user_api)):
        h = service.health()
        h["queue"] = {"pending": worker.pending()}
        h["auth_mode"] = auth.mode
        return h

    @app.get("/api/models")
    def models(user: User = Depends(user_api)):
        h = service.health()
        return {"configured": h["model"], "ollama": h["ollama"]}

    @app.get("/api/dashboard")
    def dashboard(user: User = Depends(user_api)):
        return service.dashboard(owner=owner_filter(user))

    # ------------------------------------------------------------------ API: incidents
    @app.post("/api/incidents", status_code=201)
    async def create_incident(request: Request, files: list[UploadFile] = File(...), incident_id: str = Form(...),
                              description: str = Form(...), timestamp: str = Form(...),
                              trigger_file: str = Form(...), trigger_line: int = Form(...),
                              trigger_component: str = Form(...), rule_id: Optional[str] = Form(None),
                              mode: Optional[str] = Form(None), user: User = Depends(writer)):
        lim = service.limits
        if len(files) > lim.max_files:
            raise ValidationProblem({"files": f"at most {lim.max_files} files"})
        payload, total = [], 0
        for f in files:
            content = await f.read(lim.max_file_bytes + 1)
            total += len(content)
            if total > lim.max_total_bytes:
                raise ValidationProblem({"files": f"total upload larger than {lim.max_total_bytes} bytes"})
            payload.append((f.filename or "", content))
        if mode not in (None, "", "E2b", "E3"):
            raise ValidationProblem({"mode": "must be E2b or E3"})
        inv = service.create_investigation(payload, incident_id, description, timestamp, trigger_file,
                                           trigger_line, trigger_component, rule_id=rule_id or None,
                                           owner=user.username)
        analysis = None
        if mode:
            a = service.request_analysis(inv.id, mode, requested_by=user.username)
            worker.submit(inv.id, a.run_id)
            analysis = a.model_dump(mode="json")
        return {"id": inv.id, "warnings": inv.warnings, "analysis": analysis,
                "files": [fi.model_dump() for fi in inv.log_files]}

    @app.post("/api/incidents/{inv_id}/analyze", status_code=202)
    def analyze(inv_id: str, body: AnalyzeRequest, user: User = Depends(writer)):
        load_owned(inv_id, user)
        a = service.request_analysis(inv_id, body.mode, requested_by=user.username)
        worker.submit(inv_id, a.run_id)
        return a.model_dump(mode="json")

    @app.get("/api/incidents")
    def list_incidents(incident_id: Optional[str] = None, mode: Optional[Literal["E2b", "E3"]] = None,
                       date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                       user: User = Depends(user_api)):
        def aware(d):
            return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)
        rows = service.list_investigations(incident_id=incident_id, mode=mode, date_from=aware(date_from),
                                           date_to=aware(date_to), owner=owner_filter(user))
        return [{"id": i.id, "created_at": i.created_at.isoformat(), "owner": i.owner,
                 "incident": i.incident.model_dump(mode="json"), "status": i.status,
                 "analyses": [a.model_dump(mode="json") for a in i.analyses]} for i in rows]

    @app.get("/api/incidents/{inv_id}")
    def get_incident(inv_id: str, user: User = Depends(user_api)):
        inv = load_owned(inv_id, user)
        return inv.model_dump(mode="json") | {"status": inv.status}

    @app.get("/api/incidents/{inv_id}/status")
    def status(inv_id: str, run_id: Optional[str] = None, user: User = Depends(user_api)):
        load_owned(inv_id, user)
        return service.progress(inv_id, run_id)

    def _record(inv_id: str, run_id: Optional[str]):
        try:
            return service.record(inv_id, run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/incidents/{inv_id}/report")
    def report(inv_id: str, run_id: Optional[str] = None, user: User = Depends(user_api)):
        load_owned(inv_id, user)
        return build_view(_record(inv_id, run_id), service.manifest(inv_id))

    @app.get("/api/incidents/{inv_id}/report.md")
    def report_md(inv_id: str, run_id: Optional[str] = None, user: User = Depends(user_api)):
        load_owned(inv_id, user)
        rec = _record(inv_id, run_id)
        return PlainTextResponse(to_markdown(rec, service.manifest(inv_id)), media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="{rec.run_id}.md"'})

    @app.get("/api/incidents/{inv_id}/report.json")
    def report_json(inv_id: str, run_id: Optional[str] = None, user: User = Depends(user_api)):
        load_owned(inv_id, user)
        rec = _record(inv_id, run_id)
        return Response(rec.model_dump_json(indent=1), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{rec.run_id}.json"'})

    @app.get("/api/incidents/{inv_id}/evidence")
    def evidence(inv_id: str, run_id: Optional[str] = None, user: User = Depends(user_api)):
        load_owned(inv_id, user)
        return build_view(_record(inv_id, run_id))["evidence"]

    @app.get("/api/incidents/{inv_id}/evidence/{eid}/source")
    def evidence_source(inv_id: str, eid: str, run_id: Optional[str] = None, user: User = Depends(user_api)):
        load_owned(inv_id, user)
        rec = _record(inv_id, run_id)
        item = next((e for e in rec.evidence if e.id == eid), None)
        if item is None:
            raise HTTPException(404, "unknown evidence id")
        return {"evidence": {"id": item.id, "source": item.source, "line_no": item.line_no,
                             "message_as_presented": item.message, "suspicious": item.suspicious},
                "lines": service.source_lines(inv_id, item.source, item.line_no)}

    # ------------------------------------------------------------------ login
    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, error: Optional[str] = None):
        if auth.mode == "local":
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": error, "user": None})

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...)):
        origin = request.headers.get("origin")
        if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
            raise HTTPException(403, "cross-origin login refused")
        user = auth.authenticate(username, password)
        if user is None:
            return RedirectResponse("/login?error=1", status_code=303)
        token, _ = auth.issue(user)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_S, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    # ------------------------------------------------------------------ pages
    def page(name: str, request: Request, **ctx):
        user, csrf = current(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, name, {"user": user, "csrf": csrf or "", "auth_mode": auth.mode,
                                                          "model": service.base_cfg.llm.model,
                                                          "budget": service.base_cfg.budget.evidence_token_budget,
                                                          **ctx})

    @app.get("/", response_class=HTMLResponse)
    def dashboard_page(request: Request):
        return page("dashboard.html", request)

    @app.get("/new", response_class=HTMLResponse)
    def new_page(request: Request):
        lim = service.limits
        return page("new.html", request, limits=lim)

    @app.get("/investigations", response_class=HTMLResponse)
    def history_page(request: Request):
        return page("history.html", request)

    @app.get("/investigations/{inv_id}", response_class=HTMLResponse)
    def investigation_page(request: Request, inv_id: str):
        user, _ = current(request)
        if user is not None:
            load_owned(inv_id, user)
        return page("investigation.html", request, inv_id=inv_id)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return page("settings.html", request)

    return app


def serve(config_path, workspace=None, host: str = "127.0.0.1", port: int = 8765,
          auth_file: Optional[str] = None) -> int:
    import uvicorn
    if not is_loopback(host) and not auth_file:
        print("ERROR: refusing to bind to a non-loopback address without --auth-file (authentication).",
              file=sys.stderr)
        return 2
    service = AppService(config_path=config_path, workspace=workspace)
    auth = Auth(auth_file) if auth_file else Auth()
    hosts = LOOPBACK_HOSTS if is_loopback(host) else LOOPBACK_HOSTS + [host]
    app = create_app(service, auth, allowed_hosts=hosts)
    print(f"LogAgent-RCA web UI: http://{'127.0.0.1' if is_loopback(host) else host}:{port}/  "
          f"(model {service.base_cfg.llm.model}, auth mode {auth.mode})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info", proxy_headers=False, server_header=False)
    return 0
