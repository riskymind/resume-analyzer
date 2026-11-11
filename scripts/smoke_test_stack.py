"""End-to-end smoke test of a running stack through its public entry point (nginx locally, Vercel in a preview).

    python3 -I scripts/smoke_test_stack.py http://localhost:8090            # Compose stack with the FAKE AI provider
    python3 -I scripts/smoke_test_stack.py http://localhost:8080 --no-ai    # any stack; skips AI-backed steps

Standard library only. It registers a throwaway account (smoke-<random>@example.com), uploads the synthetic sample
resume and job description that the fake AI provider has canned answers for (frontend/e2e/fixtures), creates a
rewrite, exports it as PDF and DOCX in every template, checks routing (SPA deep links vs API), CSRF and session
handling, and finally deletes the account. Against a real Gemini-backed stack the AI steps would spend credits,
so only run the full test against the fake-AI stack (compose.fake-ai.yaml); use --no-ai anywhere else.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import secrets
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "frontend" / "e2e" / "fixtures"
TEMPLATES = {"modern", "minimal", "corporate", "technical", "graduate"}
DELETE_PHRASE = "delete my account"


class Check:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def __call__(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  ok    {label}")
        else:
            self.failed.append(label)
            print(f"  FAIL  {label} {detail}")
        return ok


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        body: bytes | None = None,
        content_type: str | None = None,
        csrf: bool = True,
        timeout: float = 120,
    ) -> tuple[int, dict[str, str], bytes]:
        headers = {"Origin": self.base, "Accept": "application/json"}
        if json_body is not None:
            body = json.dumps(json_body).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        if csrf and self.csrf and method not in {"GET", "HEAD"}:
            headers["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)  # noqa: S310
        try:
            with self.opener.open(req, timeout=timeout) as res:
                return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read()
        except urllib.error.HTTPError as err:
            return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()

    def json(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        status, _, raw = self.request(method, path, **kwargs)
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, {"_raw": raw[:200].decode("utf-8", "replace")}


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data, mime) in files.items():
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        )
        parts.append(head.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def routing(client: Client, check: Check) -> None:
    print("routing")
    status, headers, raw = client.request("GET", "/rewrites/00000000-0000-0000-0000-000000000000")
    check(status == 200 and b'<div id="root">' in raw, "deep link /rewrites/<id> serves the SPA", f"({status})")
    for path in ("/resumes/x", "/matches/x", "/jobs/x", "/reviews/1", "/account", "/upload"):
        status, _, raw = client.request("GET", path)
        check(status == 200 and b'<div id="root">' in raw, f"deep link {path} serves the SPA", f"({status})")
    check(headers.get("x-frame-options") == "DENY", "security headers on the page")
    status, headers, raw = client.request("GET", "/api/v1/definitely-not-a-route")
    check(
        status == 404 and headers.get("content-type", "").startswith("application/json") and b"not_found" in raw,
        "unknown /api route is a JSON 404, not the SPA",
        f"({status} {headers.get('content-type')})",
    )
    status, _, raw = client.request("GET", "/assets/does-not-exist.js")
    check(status == 404 and b'<div id="root">' not in raw, "missing asset is a 404, not index.html", f"({status})")
    status, payload = client.json("GET", "/api/v1/health")
    check(status == 200 and payload == {"status": "ok"}, "API liveness through the proxy")
    status, headers, _ = client.request("GET", "/api/v1/health")
    check(headers.get("cache-control") == "no-store", "API responses are not cacheable")


def auth(client: Client, check: Check, email: str, password: str) -> bool:
    print("authentication and sessions")
    status, _ = client.json("GET", "/api/v1/auth/me")
    check(status == 401, "anonymous /auth/me is 401", f"({status})")
    status, payload = client.json("POST", "/api/v1/auth/register", json_body={"email": email, "password": password})
    if not check(status == 201, "register", f"({status} {payload})"):
        return False
    client.csrf = payload["csrf_token"]
    check(any(cookie.name.endswith("ra_session") for cookie in client.jar), "session cookie set through the proxy")
    status, payload = client.json("GET", "/api/v1/auth/me")
    check(status == 200 and payload["user"]["email"] == email, "session cookie authenticates /auth/me")
    status, payload = client.json("POST", "/api/v1/auth/logout", csrf=False)
    check(status == 403, "state change without CSRF token is refused", f"({status})")
    deletion = {"password": password, "confirmation": DELETE_PHRASE}
    status, _, _ = client.request("DELETE", "/api/v1/auth/me", json_body=deletion, csrf=False)
    check(status == 403, "account deletion without CSRF token is refused", f"({status})")
    return True


def journey(client: Client, check: Check) -> None:
    print("resume, job, rewrite (fake AI provider)")
    resume_bytes = (FIXTURES / "jane-doe-resume.md").read_bytes()
    body, ctype = multipart({}, {"file": ("jane-doe-resume.md", resume_bytes, "text/markdown")})
    status, resume = client.json("POST", "/api/v1/resumes", body=body, content_type=ctype)
    if not check(status == 201, "upload resume fixture", f"({status} {resume})"):
        return
    check(bool(resume.get("structured", {}).get("experience")), "resume extracted into structured data")

    body, ctype = multipart({"text": (FIXTURES / "job.txt").read_text()}, {})
    status, job = client.json("POST", "/api/v1/jobs", body=body, content_type=ctype)
    if not check(status == 201, "parse job description fixture", f"({status} {job})"):
        return
    check(len(job.get("requirements", [])) > 0, "job requirements extracted")

    status, match = client.json("POST", "/api/v1/matches", json_body={"resume_id": resume["id"], "job_id": job["id"]})
    score = match.get("report", {}).get("match_score") if status == 201 else None
    check(isinstance(score, int), "deterministic job match", f"({status} score={score})")

    status, rewrite = client.json(
        "POST",
        "/api/v1/rewrites",
        json_body={"resume_id": resume["id"], "job_id": job["id"], "mode": "job_targeted", "scope": "full"},
    )
    if not check(status == 201, "rewrite with the fake AI provider", f"({status} {rewrite})"):
        return

    status, templates = client.json("GET", "/api/v1/rewrites/templates")
    keys = {t["key"] for t in templates} if status == 200 else set()
    check(keys == TEMPLATES, "five templates available", f"({sorted(keys)})")

    print("exports")
    for template in sorted(TEMPLATES):
        for fmt, magic in (("pdf", b"%PDF-"), ("docx", b"PK\x03\x04")):
            request: dict[str, object] = {"format": fmt, "template": template}
            status, headers, raw = client.request("POST", f"/api/v1/rewrites/{rewrite['id']}/export", json_body=request)
            if status == 409:  # unverified claims need explicit acknowledgement, as in the UI
                request["acknowledge_unverified"] = True
                status, headers, raw = client.request(
                    "POST", f"/api/v1/rewrites/{rewrite['id']}/export", json_body=request
                )
            check(
                status == 200 and raw.startswith(magic) and "attachment" in headers.get("content-disposition", ""),
                f"{template} {fmt} export ({len(raw)} bytes)",
                f"({status} {raw[:120]!r})",
            )

    print("isolation")
    other = Client(client.base)
    other_account = {"email": f"smoke-{secrets.token_hex(6)}@example.com", "password": secrets.token_urlsafe(18)}
    status, payload = other.json("POST", "/api/v1/auth/register", json_body=other_account)
    if status == 201:
        other.csrf = payload["csrf_token"]
        status, _ = other.json("GET", f"/api/v1/rewrites/{rewrite['id']}")
        check(status == 404, "another account cannot read this rewrite", f"({status})")
        other.json("DELETE", "/api/v1/auth/me", json_body={**other_account, "confirmation": DELETE_PHRASE})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("base_url")
    parser.add_argument("--no-ai", action="store_true", help="skip the steps that call the AI provider")
    args = parser.parse_args(argv)

    check = Check()
    client = Client(args.base_url)
    email = f"smoke-{secrets.token_hex(6)}@example.com"
    password = secrets.token_urlsafe(18)
    routing(client, check)
    if auth(client, check, email, password):
        if not args.no_ai:
            journey(client, check)
        print("cleanup")
        status, _ = client.json(
            "DELETE", "/api/v1/auth/me", json_body={"password": password, "confirmation": DELETE_PHRASE}
        )
        check(status == 204, "delete the smoke-test account", f"({status})")
        status, _ = client.json("GET", "/api/v1/auth/me")
        check(status == 401, "session ends with the account")

    print(f"\n{check.passed} passed, {len(check.failed)} failed")
    for label in check.failed:
        print(f"  - {label}")
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
