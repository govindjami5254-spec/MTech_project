"""Authentication, roles, sessions and CSRF protection for the web adapter.

Modes:
* ``local`` (default): no login; only allowed when the server binds to a loopback address. The single implicit
  user is ``local`` with role ``admin``.
* ``users``: a users file with PBKDF2-SHA256 password hashes and roles; required for any non-loopback binding.

Roles: ``viewer`` (read own investigations), ``analyst`` (+ create and analyse), ``admin`` (+ read all
investigations). No role can change research or model settings from the web interface.

Sessions are HMAC-signed cookies (HttpOnly, SameSite=Strict). State-changing requests must carry the session's CSRF
token in ``X-CSRF-Token``; in local mode they must carry ``X-Requested-With: logagent-rca`` (a custom header that
cross-site pages cannot send without a CORS pre-flight, which this server never grants).

Users file management:  ``python -m logagent_rca.web.auth add-user --file users.json --username NAME --role analyst``
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

ROLES = ("viewer", "analyst", "admin")
Role = Literal["viewer", "analyst", "admin"]
ITERATIONS = 240_000
SESSION_COOKIE = "lrca_session"
SESSION_TTL_S = 8 * 3600
LOCAL_HEADER = ("X-Requested-With", "logagent-rca")


@dataclass(frozen=True)
class User:
    username: str
    role: Role

    def can(self, action: str) -> bool:
        need = {"read": "viewer", "write": "analyst", "read_all": "admin"}[action]
        return ROLES.index(self.role) >= ROLES.index(need)


def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = ITERATIONS) -> dict:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {"salt": salt.hex(), "iterations": iterations, "hash": dk.hex()}


def verify_password(password: str, rec: dict) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(rec["salt"]), int(rec["iterations"]))
    return hmac.compare_digest(dk.hex(), rec["hash"])


class Auth:
    def __init__(self, users_file: Optional[str | Path] = None, secret: Optional[bytes] = None):
        self.mode = "users" if users_file else "local"
        self.users: dict[str, dict] = {}
        if users_file:
            data = json.loads(Path(users_file).read_text(encoding="utf-8"))
            for u in data.get("users", []):
                if u.get("role") not in ROLES:
                    raise ValueError(f"invalid role for {u.get('username')!r}")
                self.users[u["username"]] = u
            if not self.users:
                raise ValueError("users file contains no users")
        self.secret = secret or secrets.token_bytes(32)          # sessions end when the server restarts

    # ------------------------------------------------------------------ login and sessions
    def authenticate(self, username: str, password: str) -> Optional[User]:
        rec = self.users.get(username or "")
        if rec is None:
            verify_password(password or "", hash_password("dummy", iterations=1_000))   # similar timing path
            return None
        return User(username, rec["role"]) if verify_password(password or "", rec) else None

    def issue(self, user: User) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(24)
        body = json.dumps({"u": user.username, "r": user.role, "exp": int(time.time()) + SESSION_TTL_S,
                           "csrf": csrf}, separators=(",", ":")).encode()
        sig = hmac.new(self.secret, body, hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(body).decode() + "." + base64.urlsafe_b64encode(sig).decode()
        return token, csrf

    def session(self, token: Optional[str]) -> Optional[tuple[User, str]]:
        if not token or "." not in token:
            return None
        try:
            b64body, b64sig = token.split(".", 1)
            body = base64.urlsafe_b64decode(b64body.encode())
            sig = base64.urlsafe_b64decode(b64sig.encode())
        except (ValueError, TypeError):
            return None
        if not hmac.compare_digest(hmac.new(self.secret, body, hashlib.sha256).digest(), sig):
            return None
        data = json.loads(body)
        if data.get("exp", 0) < time.time() or data.get("u") not in self.users or data.get("r") not in ROLES:
            return None
        if self.users[data["u"]]["role"] != data["r"]:            # role changed since login
            return None
        return User(data["u"], data["r"]), data["csrf"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="logagent_rca.web.auth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-user")
    a.add_argument("--file", required=True)
    a.add_argument("--username", required=True)
    a.add_argument("--role", choices=ROLES, required=True)
    args = ap.parse_args(argv)
    path = Path(args.file)
    data = json.loads(path.read_text()) if path.exists() else {"users": []}
    pw = getpass.getpass("password: ")
    if len(pw) < 12 or pw != getpass.getpass("repeat: "):
        print("password must be at least 12 characters and match", file=sys.stderr)
        return 2
    data["users"] = [u for u in data["users"] if u["username"] != args.username]
    data["users"].append({"username": args.username, "role": args.role, **hash_password(pw)})
    path.write_text(json.dumps(data, indent=1))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print(f"saved {args.username} ({args.role}) to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
