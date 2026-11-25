"""Start the real web server in-process on 127.0.0.1, request pages and health (no model inference), then stop."""
import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx, uvicorn
from logagent_rca.service import AppService
from logagent_rca.web.app import create_app, LOOPBACK_HOSTS

ws = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lrca-smoke-ws"
svc = AppService(config_path="configs/app.yaml", workspace=ws)
server = uvicorn.Server(uvicorn.Config(create_app(svc, allowed_hosts=LOOPBACK_HOSTS), host="127.0.0.1", port=8765, log_level="warning"))
t = threading.Thread(target=server.run, daemon=True); t.start()
for _ in range(100):
    if server.started: break
    time.sleep(0.1)
with httpx.Client(base_url="http://127.0.0.1:8765", timeout=20) as c:
    for p in ("/", "/new", "/investigations", "/settings", "/static/app.js"):
        print("GET", p, c.get(p).status_code)
    h = c.get("/api/health").json()
    print("health:", h["backend"], "| ollama reachable", h["ollama"]["reachable"], h["ollama"].get("version"),
          "| model installed", h["ollama"].get("configured_model_installed"), "| experiment_running", h["experiment_running"],
          "| tokenizer", h["tokenizer"]["verified"], "| workspace writable", h["persistence"]["writable"])
    print("POST without anti-CSRF header ->", c.post("/api/incidents").status_code)
    print("foreign Host header ->", c.get("/api/health", headers={"Host": "evil.example"}).status_code)
server.should_exit = True; t.join(timeout=10); print("server stopped:", not t.is_alive())
