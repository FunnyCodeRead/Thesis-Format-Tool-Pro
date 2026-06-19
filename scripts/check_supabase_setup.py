from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from jose import jwt


SERVICE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVICE_DIR.parent.parent

if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.core.config import settings  # noqa: E402


EXPECTED_TEMPLATE_KEYS = {
    "do_an_tot_nghiep",
    "khoa_luan_tot_nghiep",
    "bao_cao_thuc_tap",
}

EXPECTED_TEMPLATE_CONFIG_KEYS = {
    "page_setup",
    "paragraph",
    "list_item",
    "front_matter_heading",
    "chapter_layout",
    "pagination",
    "caption_numbering",
    "document_length",
    "character_density",
    "advanced_review",
    "render_verification",
    "scope_review",
    "content_scope",
}

TABLE_COLUMNS: dict[str, list[str]] = {
    "profiles": [
        "id",
        "email",
        "full_name",
        "avatar_url",
        "plan",
        "free_checks_used",
        "free_checks_limit",
        "created_at",
        "updated_at",
    ],
    "document_templates": [
        "id",
        "key",
        "name",
        "config_json",
        "price_vnd",
        "version",
        "is_active",
        "created_at",
        "updated_at",
    ],
    "documents": [
        "id",
        "user_id",
        "document_type",
        "original_filename",
        "original_file_key",
        "fixed_file_key",
        "report_file_key",
        "annotated_file_key",
        "status",
        "total_findings",
        "error_count",
        "warning_count",
        "last_analyzed_at",
        "last_fixed_at",
        "annotated_at",
        "fixed_at",
        "created_at",
        "updated_at",
        "expires_at",
        "deleted_at",
    ],
    "findings": [
        "id",
        "document_id",
        "type",
        "severity",
        "location",
        "message",
        "current_value",
        "expected_value",
        "suggestion",
        "metadata",
        "created_at",
    ],
    "orders": [
        "id",
        "user_id",
        "document_id",
        "amount",
        "currency",
        "status",
        "payment_provider",
        "provider_order_code",
        "checkout_url",
        "qr_code",
        "paid_at",
        "expires_at",
        "metadata",
        "created_at",
        "updated_at",
    ],
    "payment_webhook_events": [
        "id",
        "provider",
        "provider_order_code",
        "event_type",
        "event_key",
        "payload",
        "checksum",
        "processed",
        "processed_at",
        "processing_error",
        "created_at",
    ],
    "download_tokens": [
        "id",
        "user_id",
        "document_id",
        "token_hash",
        "kind",
        "expires_at",
        "used_at",
        "created_at",
    ],
}


@dataclass
class CheckResult:
    label: str
    status: str
    detail: str = ""


class CheckRecorder:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def ok(self, label: str, detail: str = "") -> None:
        self.results.append(CheckResult(label, "OK", detail))

    def warn(self, label: str, detail: str = "") -> None:
        self.results.append(CheckResult(label, "WARN", detail))

    def fail(self, label: str, detail: str = "") -> None:
        self.results.append(CheckResult(label, "FAIL", detail))

    def print(self) -> None:
        for result in self.results:
            detail = f" - {result.detail}" if result.detail else ""
            print(f"[{result.status}] {result.label}{detail}")

    @property
    def failed(self) -> bool:
        return any(result.status == "FAIL" for result in self.results)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Thesis Format Tool Pro Supabase env, Data API schema, and optional RLS smoke checks."
    )
    parser.add_argument(
        "--access-token",
        default="",
        help="Optional Supabase user access token for authenticated RLS smoke checks.",
    )
    parser.add_argument(
        "--sync-template-config",
        action="store_true",
        help=(
            "Patch document_templates.config_json from configs/school_config.json using the "
            "backend service role. This does not print secrets."
        ),
    )
    args = parser.parse_args()

    raw_env = load_env_values(
        [
            PROJECT_ROOT / ".env",
            SERVICE_DIR / ".env",
            PROJECT_ROOT / "apps" / "web" / ".env.local",
        ]
    )
    access_token = args.access_token or raw_env.get("SUPABASE_TEST_ACCESS_TOKEN", "")

    recorder = CheckRecorder()
    project_url = normalize_project_url(settings.supabase_url)

    check_env(recorder, raw_env)
    if project_url and settings.supabase_service_role_key:
        session = requests.Session()
        check_jwks(recorder, session, project_url)
        check_service_role_schema(recorder, session, project_url)
        if args.sync_template_config:
            sync_template_config(recorder, session, project_url)
        check_document_templates(recorder, session, project_url)
        check_authenticated_smoke(recorder, session, project_url, raw_env, access_token)
    else:
        recorder.fail(
            "Supabase live checks skipped",
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.",
        )

    recorder.print()
    return 1 if recorder.failed else 0


def load_env_values(paths: list[Path]) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            value = raw_value.strip().strip('"').strip("'")
            values[key] = value
    return values


def normalize_project_url(raw_url: str) -> str:
    project_url = raw_url.strip().rstrip("/")
    for suffix in ("/rest/v1", "/auth/v1"):
        if project_url.endswith(suffix):
            project_url = project_url[: -len(suffix)].rstrip("/")
    return project_url


def check_env(recorder: CheckRecorder, raw_env: dict[str, str]) -> None:
    required_backend = {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_SERVICE_ROLE_KEY": settings.supabase_service_role_key,
    }
    for key, value in required_backend.items():
        if value:
            recorder.ok(f"env {key}", "configured")
        else:
            recorder.fail(f"env {key}", "missing")

    if settings.supabase_jwt_secret:
        recorder.ok("env SUPABASE_JWT_SECRET", "configured for legacy HS256 tokens")
    else:
        recorder.warn(
            "env SUPABASE_JWT_SECRET",
            "missing; OK for ES256/RS256 Supabase projects because backend uses JWKS.",
        )

    if raw_env.get("NEXT_PUBLIC_SUPABASE_URL"):
        recorder.ok("env NEXT_PUBLIC_SUPABASE_URL", "configured")
    else:
        recorder.warn("env NEXT_PUBLIC_SUPABASE_URL", "missing from scanned env files")

    if raw_env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"):
        recorder.ok("env NEXT_PUBLIC_SUPABASE_ANON_KEY", "configured")
    else:
        recorder.warn("env NEXT_PUBLIC_SUPABASE_ANON_KEY", "missing; authenticated smoke checks need it")


def service_headers() -> dict[str, str]:
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Accept": "application/json",
    }


def user_headers(raw_env: dict[str, str], access_token: str) -> dict[str, str]:
    anon_key = raw_env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
    return {
        "apikey": anon_key,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def rest_get(
    session: requests.Session,
    project_url: str,
    table: str,
    *,
    headers: dict[str, str],
    params: dict[str, str],
) -> requests.Response:
    return session.get(
        f"{project_url}/rest/v1/{table}",
        headers=headers,
        params=params,
        timeout=20,
    )


def check_jwks(recorder: CheckRecorder, session: requests.Session, project_url: str) -> None:
    try:
        response = session.get(
            f"{project_url}/auth/v1/.well-known/jwks.json",
            headers={"Accept": "application/json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        recorder.fail("Supabase JWKS", f"request failed: {exc.__class__.__name__}")
        return

    if not response.ok:
        recorder.fail("Supabase JWKS", f"HTTP {response.status_code}")
        return

    try:
        payload = response.json()
    except ValueError:
        recorder.fail("Supabase JWKS", "response is not JSON")
        return

    if isinstance(payload, dict) and isinstance(payload.get("keys"), list) and payload["keys"]:
        algorithms = sorted({str(key.get("alg")) for key in payload["keys"] if key.get("alg")})
        recorder.ok("Supabase JWKS", f"{len(payload['keys'])} key(s), alg={','.join(algorithms)}")
    else:
        recorder.fail("Supabase JWKS", "missing keys array")


def check_service_role_schema(
    recorder: CheckRecorder,
    session: requests.Session,
    project_url: str,
) -> None:
    for table, columns in TABLE_COLUMNS.items():
        response = rest_get(
            session,
            project_url,
            table,
            headers=service_headers(),
            params={"select": ",".join(columns), "limit": "0"},
        )
        if response.ok:
            recorder.ok(f"Data API schema {table}", f"{len(columns)} expected column(s) visible")
        else:
            recorder.fail(
                f"Data API schema {table}",
                summarize_error_response(response),
            )


def check_document_templates(
    recorder: CheckRecorder,
    session: requests.Session,
    project_url: str,
) -> None:
    response = rest_get(
        session,
        project_url,
        "document_templates",
        headers=service_headers(),
        params={
            "select": "key,version,is_active,price_vnd,config_json",
            "key": f"in.({','.join(sorted(EXPECTED_TEMPLATE_KEYS))})",
        },
    )
    if not response.ok:
        recorder.fail("document_templates seed/config", summarize_error_response(response))
        return

    try:
        rows = response.json()
    except ValueError:
        recorder.fail("document_templates seed/config", "response is not JSON")
        return

    rows_by_key = {row.get("key"): row for row in rows if isinstance(row, dict)}
    missing = sorted(EXPECTED_TEMPLATE_KEYS - set(rows_by_key))
    if missing:
        recorder.fail("document_templates seed/config", f"missing template(s): {', '.join(missing)}")
        return

    for key in sorted(EXPECTED_TEMPLATE_KEYS):
        row = rows_by_key[key]
        version = int(row.get("version") or 0)
        config = row.get("config_json") if isinstance(row.get("config_json"), dict) else {}
        missing_config = sorted(EXPECTED_TEMPLATE_CONFIG_KEYS - set(config))
        if version < 6:
            recorder.fail(f"template {key}", f"version {version}; expected >= 6")
        elif missing_config:
            recorder.fail(f"template {key}", f"missing config keys: {', '.join(missing_config)}")
        elif config.get("content_scope", {}).get("enabled") is not False:
            recorder.fail(f"template {key}", "content_scope.enabled must stay false by default")
        else:
            recorder.ok(f"template {key}", f"version {version}, price_vnd={row.get('price_vnd')}")


def sync_template_config(
    recorder: CheckRecorder,
    session: requests.Session,
    project_url: str,
) -> None:
    config_path = PROJECT_ROOT / "configs" / "school_config.json"
    try:
        local_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        recorder.fail("sync template config", f"cannot read local config: {exc.__class__.__name__}")
        return

    now = datetime.now(timezone.utc).isoformat()
    for key in sorted(EXPECTED_TEMPLATE_KEYS):
        config_json = local_config.get(key)
        if not isinstance(config_json, dict):
            recorder.fail(f"sync template {key}", "missing local config object")
            continue

        response = requests.patch(
            f"{project_url}/rest/v1/document_templates",
            headers={
                **service_headers(),
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            params={"key": f"eq.{key}"},
            json={
                "config_json": config_json,
                "version": 7,
                "updated_at": now,
            },
            timeout=20,
        )
        if response.ok:
            recorder.ok(f"sync template {key}", "config_json updated from local config")
        else:
            recorder.fail(f"sync template {key}", summarize_error_response(response))


def check_authenticated_smoke(
    recorder: CheckRecorder,
    session: requests.Session,
    project_url: str,
    raw_env: dict[str, str],
    access_token: str,
) -> None:
    if not access_token:
        recorder.warn(
            "authenticated RLS smoke",
            "skipped; set SUPABASE_TEST_ACCESS_TOKEN or pass --access-token.",
        )
        return
    if not raw_env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"):
        recorder.warn(
            "authenticated RLS smoke",
            "skipped; NEXT_PUBLIC_SUPABASE_ANON_KEY is required as Data API apikey.",
        )
        return

    headers = user_headers(raw_env, access_token)
    user_id = unverified_sub(access_token)
    if user_id:
        recorder.ok("test access token", "contains a subject claim")
    else:
        recorder.warn("test access token", "could not read subject claim")

    templates_response = rest_get(
        session,
        project_url,
        "document_templates",
        headers=headers,
        params={"select": "key", "is_active": "eq.true", "limit": "1"},
    )
    if templates_response.ok:
        recorder.ok("authenticated Data API document_templates", "active templates readable")
    else:
        recorder.fail(
            "authenticated Data API document_templates",
            summarize_error_response(templates_response),
        )

    documents_response = rest_get(
        session,
        project_url,
        "documents",
        headers=headers,
        params={"select": "id,user_id", "limit": "5"},
    )
    if not documents_response.ok:
        recorder.fail("authenticated RLS documents", summarize_error_response(documents_response))
    else:
        rows = safe_json_list(documents_response)
        foreign_rows = [
            row
            for row in rows
            if user_id and isinstance(row, dict) and str(row.get("user_id")) != user_id
        ]
        if foreign_rows:
            recorder.fail(
                "authenticated RLS documents",
                f"returned {len(foreign_rows)} row(s) for another user",
            )
        else:
            recorder.ok("authenticated RLS documents", f"returned {len(rows)} owned row(s)")

    webhook_response = rest_get(
        session,
        project_url,
        "payment_webhook_events",
        headers=headers,
        params={"select": "id", "limit": "1"},
    )
    if webhook_response.ok:
        recorder.fail(
            "authenticated RLS payment_webhook_events",
            "authenticated role can read webhook event table",
        )
    elif webhook_response.status_code in {401, 403, 404}:
        recorder.ok(
            "authenticated RLS payment_webhook_events",
            f"blocked with HTTP {webhook_response.status_code}",
        )
    else:
        recorder.warn(
            "authenticated RLS payment_webhook_events",
            summarize_error_response(webhook_response),
        )


def unverified_sub(access_token: str) -> str | None:
    try:
        claims = jwt.get_unverified_claims(access_token)
    except Exception:
        return None
    sub = claims.get("sub") if isinstance(claims, dict) else None
    return str(sub) if sub else None


def safe_json_list(response: requests.Response) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        return []
    return payload if isinstance(payload, list) else []


def summarize_error_response(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict):
        code = payload.get("code")
        message = payload.get("message") or payload.get("msg")
        hint = payload.get("hint")
        parts = [str(part) for part in (code, message, hint) if part]
        if parts:
            return f"HTTP {response.status_code}: {' | '.join(parts)}"
    if isinstance(payload, str) and payload.strip():
        return f"HTTP {response.status_code}: {payload[:240]}"
    return f"HTTP {response.status_code}"


if __name__ == "__main__":
    raise SystemExit(main())
