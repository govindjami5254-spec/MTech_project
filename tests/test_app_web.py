"""Web adapter tests (FastAPI TestClient, scripted LLM, no Ollama inference)."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app_helpers import ROOT, dev_inputs, scripted_llm
from logagent_rca.__main__ import main as cli_main
from logagent_rca.service import AppService, UploadLimits
from logagent_rca.web.app import create_app, serve
from logagent_rca.web.auth import SESSION_COOKIE, Auth, hash_password
from logagent_rca.web.jobs import JobWorker

H = {"X-Requested-With": "logagent-rca"}


def fake_request(self, path, body=None, timeout=None):
    if path == "/api/version":
        return {"version": "0.40.16"}
    if path == "/api/tags":
        return {"models": [{"name": "qwen3:8b", "size": 5225374496, "digest": "b3d9ba7c899c"}]}
    raise AssertionError(f"unexpected Ollama call {path}")


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    import logagent_rca.service as service
    monkeypatch.setattr(service.OllamaClient, "_request", fake_request)
    return AppService(workspace=tmp_path / "ws", llm_factory=lambda cfg: scripted_llm(), experiment_guard=lambda: False)


@pytest.fixture()
def client(svc):
    with TestClient(create_app(svc)) as c:
        yield c


def form(inp, mode="E3", **over):
    data = {"incident_id": inp["incident_id"], "description": inp["description"], "timestamp": inp["timestamp"],
            "trigger_file": inp["trigger_file"], "trigger_line": str(inp["trigger_line"]),
            "trigger_component": inp["trigger_component"], "rule_id": inp["rule_id"], "mode": mode}
    data.update(over)
    return data


def upload(client, inp=None, mode="E3", files=None, headers=H, **over):
    inp = inp or dev_inputs()
    files = files if files is not None else [("files", (n, c, "text/plain")) for n, c in inp["files"]]
    return client.post("/api/incidents", data=form(inp, mode, **over), files=files, headers=headers)


def finish(client):
    client.app.state.worker.drain()


# ------------------------------------------------------------------ pages, headers, health
@pytest.mark.parametrize("path", ["/", "/new", "/investigations", "/settings"])
def test_pages_render_with_security_headers(client, path):
    r = client.get(path)
    assert r.status_code == 200 and "LogAgent-RCA" in r.text and "qwen3:8b" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_health_models_dashboard(client):
    h = client.get("/api/health").json()
    assert h["ollama"]["reachable"] and h["ollama"]["configured_model_installed"]
    assert h["model"]["model"] == "qwen3:8b" and h["budget"]["evidence_token_budget"] == 900
    assert h["persistence"]["writable"] and h["tokenizer"]["verified"] and h["auth_mode"] == "local"
    assert client.get("/api/models").json()["configured"]["temperature"] == 0.2
    assert client.get("/api/dashboard").json()["investigations"] == 0


def test_untrusted_host_header_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


# ------------------------------------------------------------------ end-to-end flow
def test_upload_analyze_report_evidence_downloads(client):
    r = upload(client, mode="E3")
    assert r.status_code == 201, r.text
    inv = r.json()["id"]
    finish(client)
    st = client.get(f"/api/incidents/{inv}/status").json()
    assert st["analysis"]["status"] == "ok"
    kinds = [e["kind"] for e in st["events"]]
    assert {"input_validated", "logs_ingested", "analysis_queued", "analysis_started", "report_validated",
            "analysis_finished"} <= set(kinds)
    assert any(e["kind"] == "tool_call" for e in st["agent_events"])
    rep = client.get(f"/api/incidents/{inv}/report").json()
    assert rep["mode"] == "E3" and rep["hypotheses"] and rep["validation"]["fabricated_ids"] == 1
    assert rep["notes"]["confidence"].startswith("Confidence is the model's own")
    eid = rep["hypotheses"][0]["claims"][0]["evidence"][0]["id"]
    src = client.get(f"/api/incidents/{inv}/evidence/{eid}/source").json()
    target = [l for l in src["lines"] if l["target"]]
    assert len(target) == 1 and target[0]["line_no"] == src["evidence"]["line_no"]
    assert client.get(f"/api/incidents/{inv}/evidence").json()[0]["id"] == "E1"
    md = client.get(f"/api/incidents/{inv}/report.md")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"] and "# RCA report" in md.text
    js = client.get(f"/api/incidents/{inv}/report.json")
    assert json.loads(js.text)["run_id"] == rep["run_id"]
    r2 = client.post(f"/api/incidents/{inv}/analyze", json={"mode": "E2b"}, headers=H)
    assert r2.status_code == 202
    finish(client)
    hist = client.get("/api/incidents", params={"mode": "E2b"}).json()
    assert [h["id"] for h in hist] == [inv] and len(hist[0]["analyses"]) == 2
    assert client.get("/api/incidents", params={"incident_id": "INC-999"}).json() == []
    assert client.get(f"/investigations/{inv}").status_code == 200


def test_cli_and_web_produce_identical_reports(client, svc, tmp_path, monkeypatch, capsys):
    """Same inputs and settings -> same validated report and evidence through CLI and web."""
    import logagent_rca.service as service
    r = upload(client, mode="E3")
    inv_web = r.json()["id"]
    finish(client)
    web = svc.record(inv_web)
    monkeypatch.setattr(service, "OllamaClient", lambda cfg: scripted_llm())
    monkeypatch.setattr(service, "experiment_running", lambda: False)
    inp = dev_inputs()
    args = []
    for n, c in inp["files"]:
        (tmp_path / n).write_bytes(c)
        args += ["--log", str(tmp_path / n)]
    rc = cli_main(["diagnose", "--workspace", str(tmp_path / "ws"), *args, "--incident-id", inp["incident_id"],
                   "--description", inp["description"], "--time", inp["timestamp"], "--trigger-file",
                   inp["trigger_file"], "--trigger-line", str(inp["trigger_line"]), "--trigger-component",
                   inp["trigger_component"], "--rule-id", inp["rule_id"], "--mode", "E3"])
    assert rc == 0
    inv_cli = re.search(r"investigation (inv-\S+) created", capsys.readouterr().out).group(1)
    cli = svc.record(inv_cli)
    assert cli.report_validated == web.report_validated and cli.report_raw == web.report_raw
    assert [e.model_dump(exclude={"uid", "source"}) for e in cli.evidence] == \
           [e.model_dump(exclude={"uid", "source"}) for e in web.evidence]
    assert [e.uid for e in cli.evidence] == [e.uid for e in web.evidence]
    assert cli.model == web.model and cli.metrics.evidence_token_budget == web.metrics.evidence_token_budget
    # both records are visible through the same persistence layer
    assert {i["id"] for i in client.get("/api/incidents").json()} == {inv_web, inv_cli}


# ------------------------------------------------------------------ validation and upload security
def test_csrf_header_required(client):
    assert upload(client, headers={}).status_code == 403


@pytest.mark.parametrize("over,key", [({"incident_id": "bad"}, "incident_id"), ({"timestamp": "2026-01-10T10:00"}, "timestamp"),
                                      ({"trigger_line": "0"}, "trigger_line"), ({"trigger_component": "x"}, "trigger_component"),
                                      ({"mode": "E9"}, "mode")])
def test_invalid_fields_return_422_with_field_errors(client, over, key):
    r = upload(client, **over)
    assert r.status_code == 422 and key in r.json()["errors"]


@pytest.mark.parametrize("files,key_fragment", [
    ([("files", ("evil.exe", b"2026-01-10T10:00:00Z ERROR a b\n", "x"))], "evil.exe"),
    ([("files", ("bin.log", b"\x00\x01\x02", "x"))], "bin.log"),
    ([("files", ("empty.log", b"", "x"))], "empty.log"),
    ([("files", (".hidden.log", b"x\n", "x"))], ".hidden.log"),
])
def test_upload_content_rules(client, files, key_fragment):
    r = upload(client, files=files, trigger_file=files[0][1][0])
    assert r.status_code == 422 and any(key_fragment in k for k in r.json()["errors"])


def test_path_traversal_filename_is_sanitised_and_contained(client, svc):
    inp = dev_inputs()
    name, content = inp["files"][0]
    files = [("files", (f"../../../tmp/{n}" if n == name else n, c, "x")) for n, c in inp["files"]]
    r = upload(client, inp=inp, files=files)
    assert r.status_code == 201, r.text
    inv = r.json()["id"]
    assert (svc.store.case_dir(inv) / name).is_file()
    assert sorted(p.name for p in svc.store.case_dir(inv).iterdir()) == sorted(["incident.json"] + [n for n, _ in inp["files"]])
    assert all("/" not in f["name"] for f in r.json()["files"])


def test_size_and_count_limits(svc):
    svc.limits = UploadLimits(max_files=1, max_file_bytes=100, max_total_bytes=150, max_lines=2)
    with TestClient(create_app(svc)) as c:
        two = [("files", ("a.log", b"x\n", "x")), ("files", ("b.log", b"y\n", "x"))]
        assert "files" in upload(c, files=two, trigger_file="a.log").json()["errors"]
        big = [("files", ("a.log", b"x" * 101, "x"))]
        assert upload(c, files=big, trigger_file="a.log").status_code == 422
        lines = [("files", ("a.log", b"1\n2\n3\n", "x"))]
        assert "more than 2 lines" in json.dumps(upload(c, files=lines, trigger_file="a.log").json())
        huge = c.post("/api/incidents", content=b"x" * 10, headers={**H, "Content-Length": str(10**9),
                                                                      "Content-Type": "multipart/form-data; boundary=x"})
        assert huge.status_code == 413


def test_log_content_is_not_rendered_server_side(client):
    inp = dev_inputs()
    name, content = inp["files"][0]
    payload = content + b"2026-01-10T10:05:30Z ERROR " + inp["trigger_component"].encode() + b" <script>alert(1)</script>\n"
    inp["files"][0] = (name, payload)
    r = upload(client, inp=inp, mode="E2b")
    inv = r.json()["id"]
    finish(client)
    page = client.get(f"/investigations/{inv}").text
    assert "<script>alert(1)</script>" not in page               # pages are shells; data comes as JSON
    assert client.get(f"/api/incidents/{inv}/report").headers["content-type"].startswith("application/json")


def test_analyze_conflict_and_unknown(client):
    inv = upload(client, mode="E3").json()["id"]
    assert client.post(f"/api/incidents/{inv}/analyze", json={"mode": "E2b"}, headers=H).status_code in (202, 409)
    finish(client)
    assert client.post(f"/api/incidents/{inv}/analyze", json={"mode": "X"}, headers=H).status_code == 422
    assert client.get("/api/incidents/inv-20990101-deadbeef").status_code == 404
    assert client.get("/api/incidents/../../etc").status_code == 404
    assert client.get(f"/api/incidents/{inv}/evidence/E999/source").status_code == 404


def test_report_before_analysis_is_404(client, svc):
    inv = svc.create_investigation(**dev_inputs())
    assert client.get(f"/api/incidents/{inv.id}/report").status_code == 404


def test_refused_while_experiment_running(tmp_path, monkeypatch):
    import logagent_rca.service as service
    monkeypatch.setattr(service.OllamaClient, "_request", fake_request)
    s = AppService(workspace=tmp_path / "ws", llm_factory=lambda c: scripted_llm(), experiment_guard=lambda: True)
    with TestClient(create_app(s)) as c:
        inv = upload(c).json()["id"]
        finish(c)
        st = c.get(f"/api/incidents/{inv}/status").json()
        assert st["analysis"]["status"] == "error" and any(e["kind"] == "analysis_refused" for e in st["events"])
        assert c.get("/api/health").json()["experiment_running"] is True


def test_worker_recovery_after_restart(svc):
    inv = svc.create_investigation(**dev_inputs())
    a = svc.request_analysis(inv.id, "E2b")
    svc._set(inv.id, a.run_id, status="running")
    inv2 = svc.create_investigation(**dev_inputs())
    b = svc.request_analysis(inv2.id, "E2b")
    w = JobWorker(svc)
    w.start()
    w.drain()
    w.stop()
    assert svc.store.load(inv.id).analyses[0].status == "error"
    assert svc.store.load(inv2.id).analyses[0].status == "ok"


# ------------------------------------------------------------------ authentication and authorisation
@pytest.fixture()
def users_file(tmp_path):
    users = [{"username": u, "role": r, **hash_password(f"{u}-password-123", iterations=1000)}
             for u, r in (("alice", "analyst"), ("bob", "analyst"), ("vera", "viewer"), ("ada", "admin"))]
    p = tmp_path / "users.json"
    p.write_text(json.dumps({"users": users}))
    return p


def login(c, user):
    r = c.post("/login", data={"username": user, "password": f"{user}-password-123"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = c.get("/new").text
    return re.search(r'name="csrf-token" content="([^"]*)"', page).group(1)


def test_auth_required_and_roles(svc, users_file):
    with TestClient(create_app(svc, Auth(users_file))) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
        assert c.post("/login", data={"username": "alice", "password": "wrong"}, follow_redirects=False).headers["location"] == "/login?error=1"
        csrf = login(c, "alice")
        assert upload(c, headers={}).status_code == 403                                   # no CSRF token
        assert upload(c, headers={"X-CSRF-Token": "forged"}).status_code == 403
        r = upload(c, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 201
        inv = r.json()["id"]
        finish(c)
        assert c.get(f"/api/incidents/{inv}/report").status_code == 200
        c.cookies.clear()
        login(c, "bob")
        assert c.get(f"/api/incidents/{inv}").status_code == 404                          # isolation between users
        assert c.get("/api/incidents").json() == []
        c.cookies.clear()
        vcsrf = login(c, "vera")
        assert upload(c, headers={"X-CSRF-Token": vcsrf}).status_code == 403              # viewer cannot write
        c.cookies.clear()
        login(c, "ada")
        assert c.get(f"/api/incidents/{inv}").status_code == 200                          # admin reads all


def test_tampered_or_expired_session_rejected(users_file):
    a = Auth(users_file)
    from logagent_rca.web.auth import User
    token, _ = a.issue(User("alice", "analyst"))
    assert a.session(token)[0].username == "alice"
    body, sig = token.split(".")
    assert a.session(body + "." + sig[:-2] + "AA") is None
    assert Auth(users_file).session(token) is None                                         # different secret
    assert a.session("garbage") is None


def test_serve_refuses_public_bind_without_auth(capsys):
    assert serve("configs/app.yaml", host="0.0.0.0", port=9) == 2
    assert "refusing" in capsys.readouterr().err


def test_web_does_not_expose_research_settings_changes(client):
    paths = {r.path for r in client.app.routes}
    assert not any("settings" in p and p.startswith("/api") for p in paths)
    assert all(m in ("GET", "HEAD") for r in client.app.routes if getattr(r, "path", "") == "/settings"
               for m in r.methods)
