"""
FastAPI backend for the Job Agent Telegram Web App.
Serves the TWA and exposes REST endpoints for job management.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import unquote, parse_qsl

import httpx

from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.database.db import (
    get_pending_jobs, get_approved_jobs, get_job, update_job_status,
)
from src.cv_adapter.cv_renderer import render_to_pdf
from src.scheduler.scheduler import load_profiles

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "cvs"
PROFILES_DIR = Path(__file__).parent.parent / "profile"

app = FastAPI(title="Job Agent WebApp API")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class NgrokBypassMiddleware(BaseHTTPMiddleware):
    """Sets the ngrok browser-warning bypass cookie on every response."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.set_cookie("ngrok.skipBrowserWarning", "true", max_age=60 * 60 * 24 * 365)
        return response

app.add_middleware(NgrokBypassMiddleware)


def _verify_telegram_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData signature."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", "")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    user_str = parsed.get("user", "{}")
    return json.loads(unquote(user_str))


def _get_profile_by_telegram_id(telegram_id: int) -> dict | None:
    for config_path in PROFILES_DIR.glob("*/config.json"):
        cfg = json.loads(config_path.read_text())
        if cfg.get("telegram_chat_id") == telegram_id:
            profile_path = config_path.parent / "profile.json"
            profile_data = json.loads(profile_path.read_text()) if profile_path.exists() else {}
            return {**cfg, "profile_data": profile_data}
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/profile")
async def get_profile(x_init_data: str = Header(None)):
    if not x_init_data:
        raise HTTPException(401, "Missing init data")
    user = _verify_telegram_init_data(x_init_data)
    if not user:
        raise HTTPException(403, "Invalid init data")

    profile = _get_profile_by_telegram_id(user["id"])
    if not profile:
        raise HTTPException(404, "Profile not configured")

    return {"id": profile["id"], "name": profile["name"], "telegram_id": user["id"]}


@app.get("/api/jobs")
async def list_jobs(
    status: str = Query("pending"),
    x_init_data: str = Header(None),
):
    if not x_init_data:
        raise HTTPException(401, "Missing init data")
    user = _verify_telegram_init_data(x_init_data)
    if not user:
        raise HTTPException(403, "Invalid init data")

    profile = _get_profile_by_telegram_id(user["id"])
    if not profile:
        raise HTTPException(404, "Profile not configured")

    if status == "approved":
        jobs = await get_approved_jobs(profile["id"], limit=20)
    else:
        jobs = await get_pending_jobs(profile["id"])

    return [
        {
            "id": j["id"],
            "title": j["title"],
            "company": j["company"],
            "match_score": j["match_score"],
            "match_summary": j.get("match_summary", ""),
            "salary_info": j.get("salary_info") or j.get("salary", ""),
            "is_remote": j.get("is_remote", False),
            "requires_english": j.get("requires_english", False),
            "source": j.get("source", ""),
            "url": j["url"],
            "status": j["status"],
            "recommendation": j.get("recommendation", "Consider"),
            "skills_match": j.get("skills_match", []),
            "skills_missing": j.get("skills_missing", []),
        }
        for j in jobs
    ]


@app.post("/api/jobs/{job_id}/action")
async def job_action(
    job_id: str,
    body: dict,
    x_init_data: str = Header(None),
):
    if not x_init_data:
        raise HTTPException(401, "Missing init data")
    user = _verify_telegram_init_data(x_init_data)
    if not user:
        raise HTTPException(403, "Invalid init data")

    profile = _get_profile_by_telegram_id(user["id"])
    if not profile:
        raise HTTPException(404, "Profile not configured")

    action = body.get("action")
    if action not in ("approve", "reject", "later"):
        raise HTTPException(400, "Invalid action")

    status_map = {"approve": "approved", "reject": "rejected", "later": "pending"}
    await update_job_status(job_id, profile["id"], status_map[action])
    return {"ok": True}


@app.get("/api/jobs/{job_id}/cv")
async def download_cv(job_id: str, x_init_data: str = Header(None)):
    if not x_init_data:
        raise HTTPException(401, "Missing init data")
    user = _verify_telegram_init_data(x_init_data)
    if not user:
        raise HTTPException(403, "Invalid init data")

    profile = _get_profile_by_telegram_id(user["id"])
    if not profile:
        raise HTTPException(404, "Profile not configured")

    job = await get_job(job_id, profile["id"])
    if not job or not job.get("cv_adapted"):
        raise HTTPException(404, "CV not found")

    cfg = json.loads((PROFILES_DIR / profile["id"] / "config.json").read_text())
    candidate_name = cfg.get("name", profile["id"])
    filepath = render_to_pdf(job["cv_adapted"], job["title"], job["company"], candidate_name)

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type="application/pdf",
    )


@app.post("/api/jobs/{job_id}/send-cv")
async def send_cv_to_chat(job_id: str, x_init_data: str = Header(None)):
    """Generate CV PDF and send it directly to the user's Telegram chat."""
    if not x_init_data:
        raise HTTPException(401, "Missing init data")
    user = _verify_telegram_init_data(x_init_data)
    if not user:
        raise HTTPException(403, "Invalid init data")

    profile = _get_profile_by_telegram_id(user["id"])
    if not profile:
        raise HTTPException(404, "Profile not configured")

    job = await get_job(job_id, profile["id"])
    if not job or not job.get("cv_adapted"):
        raise HTTPException(404, "CV not found")

    cfg = json.loads((PROFILES_DIR / profile["id"] / "config.json").read_text())
    candidate_name = cfg.get("name", profile["id"])
    filepath = render_to_pdf(job["cv_adapted"], job["title"], job["company"], candidate_name)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = user["id"]
    async with httpx.AsyncClient() as client:
        with open(filepath, "rb") as f:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendDocument",
                data={"chat_id": chat_id, "caption": f"📄 CV — {job['title']} @ {job['company']}"},
                files={"document": (filepath.name, f, "application/pdf")},
                timeout=30,
            )
    if not resp.is_success:
        raise HTTPException(500, f"Telegram error: {resp.text}")

    return {"ok": True}
