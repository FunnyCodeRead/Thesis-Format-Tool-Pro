from __future__ import annotations

import shutil
import importlib.util
from typing import Any

from fastapi import APIRouter, Response, status

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def read_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "api",
        "environment": settings.app_env,
    }


@router.get("/ready")
def read_readiness(response: Response) -> dict[str, Any]:
    checks = [
        _required_group(
            "supabase_data_api",
            {
                "SUPABASE_URL": settings.supabase_url,
                "SUPABASE_SERVICE_ROLE_KEY": settings.supabase_service_role_key,
            },
        ),
        _required_group(
            "supabase_auth",
            {
                "SUPABASE_URL": settings.supabase_url,
            },
        ),
        _required_group(
            "r2_storage",
            {
                "R2_ACCOUNT_ID": settings.r2_account_id,
                "R2_ACCESS_KEY_ID": settings.r2_access_key_id,
                "R2_SECRET_ACCESS_KEY": settings.r2_secret_access_key,
                "R2_BUCKET_NAME": settings.r2_bucket_name,
            },
        ),
        _required_group(
            "payos",
            {
                "PAYOS_CLIENT_ID": settings.payos_client_id,
                "PAYOS_API_KEY": settings.payos_api_key,
                "PAYOS_CHECKSUM_KEY": settings.payos_checksum_key,
            },
        ),
        _required_group(
            "public_app_url",
            {
                "APP_PUBLIC_BASE_URL": settings.app_public_base_url,
            },
        ),
        _required_group(
            "cors",
            {
                "CORS_ORIGINS": ",".join(settings.allowed_cors_origins),
            },
        ),
        _optional_check(
            "libreoffice_render",
            bool(shutil.which("soffice") or shutil.which("libreoffice")),
            "LibreOffice is optional. Render verification is skipped when it is unavailable.",
        ),
        _optional_check(
            "pdf_render_reader",
            bool(importlib.util.find_spec("pdfplumber") or importlib.util.find_spec("pypdf")),
            "pdfplumber or pypdf is optional. Render verification is skipped when no PDF reader is available.",
        ),
    ]

    ready = all(check["ok"] for check in checks if check["required"])
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if ready else "not_ready",
        "service": "api",
        "environment": settings.app_env,
        "checks": checks,
    }


def _required_group(name: str, values: dict[str, str]) -> dict[str, Any]:
    missing = [key for key, value in values.items() if not _has_value(value)]
    return {
        "name": name,
        "required": True,
        "ok": not missing,
        "missing": missing,
    }


def _optional_check(name: str, ok: bool, note: str) -> dict[str, Any]:
    return {
        "name": name,
        "required": False,
        "ok": ok,
        "missing": [],
        "note": note,
    }


def _has_value(value: str | None) -> bool:
    return bool(value and value.strip())
