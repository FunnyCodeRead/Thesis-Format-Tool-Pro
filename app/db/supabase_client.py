from __future__ import annotations

from functools import lru_cache
from typing import Any

import requests

from app.core.config import settings


class SupabaseAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _supabase_project_url(raw_url: str) -> str:
    project_url = raw_url.strip().rstrip("/")
    for suffix in ("/rest/v1", "/auth/v1"):
        if project_url.endswith(suffix):
            project_url = project_url[: -len(suffix)].rstrip("/")
            break
    if not project_url:
        raise SupabaseAPIError(
            "SUPABASE_URL must be the Supabase project URL, not only a REST or Auth path.",
            status_code=500,
        )
    return project_url


class SupabaseRestClient:
    def __init__(self) -> None:
        if not settings.supabase_url:
            raise SupabaseAPIError("SUPABASE_URL is not configured.", status_code=500)
        if not settings.supabase_service_role_key:
            raise SupabaseAPIError(
                "SUPABASE_SERVICE_ROLE_KEY is not configured.",
                status_code=500,
            )

        self._base_url = f"{_supabase_project_url(settings.supabase_url)}/rest/v1"
        self._headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Accept": "application/json",
        }
        self._session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = dict(self._headers)
        if prefer:
            headers["Prefer"] = prefer
        url = f"{self._base_url}/{path.lstrip('/')}"
        response = self._session.request(
            method,
            url,
            params=params,
            json=json,
            headers=headers,
            timeout=30,
        )
        if not response.ok:
            raise SupabaseAPIError(
                f"Supabase REST request failed for {url}: {response.status_code} {response.text}",
                status_code=502,
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _filter_params(self, filters: dict[str, Any]) -> dict[str, str]:
        return {column: f"eq.{value}" for column, value in filters.items()}

    def select_one(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        columns: str = "*",
    ) -> dict[str, Any] | None:
        params = self._filter_params(filters)
        params["select"] = columns
        rows = self._request("GET", table, params=params)
        if not rows:
            return None
        return rows[0]

    def select_many(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params = self._filter_params(filters)
        params["select"] = columns
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        rows = self._request("GET", table, params=params)
        return rows or []

    def insert_one(
        self,
        table: str,
        *,
        payload: dict[str, Any],
        columns: str = "*",
    ) -> dict[str, Any]:
        rows = self._request(
            "POST",
            table,
            params={"select": columns},
            json=payload,
            prefer="return=representation",
        )
        if not rows:
            raise SupabaseAPIError(f"Insert returned no rows for {table}.", status_code=502)
        return rows[0]

    def insert_one_if_absent(
        self,
        table: str,
        *,
        payload: dict[str, Any],
        on_conflict: str,
        columns: str = "*",
    ) -> dict[str, Any] | None:
        rows = self._request(
            "POST",
            table,
            params={"select": columns, "on_conflict": on_conflict},
            json=payload,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        if not rows:
            return None
        return rows[0]

    def insert_many(
        self,
        table: str,
        *,
        payloads: list[dict[str, Any]],
        columns: str = "*",
        return_rows: bool = False,
    ) -> list[dict[str, Any]]:
        if not payloads:
            return []

        rows = self._request(
            "POST",
            table,
            params={"select": columns} if return_rows else None,
            json=payloads,
            prefer="return=representation" if return_rows else "return=minimal",
        )
        return rows or []

    def update_one(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        payload: dict[str, Any],
        columns: str = "*",
    ) -> dict[str, Any]:
        params = self._filter_params(filters)
        params["select"] = columns
        rows = self._request(
            "PATCH",
            table,
            params=params,
            json=payload,
            prefer="return=representation",
        )
        if not rows:
            raise SupabaseAPIError(f"Update returned no rows for {table}.", status_code=502)
        return rows[0]

    def update_maybe_one(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        payload: dict[str, Any],
        columns: str = "*",
        raw_filters: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        params = self._filter_params(filters)
        params.update(raw_filters or {})
        params["select"] = columns
        rows = self._request(
            "PATCH",
            table,
            params=params,
            json=payload,
            prefer="return=representation",
        )
        if not rows:
            return None
        return rows[0]

    def update_many(
        self,
        table: str,
        *,
        filters: dict[str, Any],
        payload: dict[str, Any],
        columns: str = "*",
        raw_filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        params = self._filter_params(filters)
        params.update(raw_filters or {})
        params["select"] = columns
        rows = self._request(
            "PATCH",
            table,
            params=params,
            json=payload,
            prefer="return=representation",
        )
        return rows or []

    def delete_many(self, table: str, *, filters: dict[str, Any]) -> None:
        self._request(
            "DELETE",
            table,
            params=self._filter_params(filters),
            prefer="return=minimal",
        )
        
    def rpc(self, function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._request(
            "POST",
            f"rpc/{function_name}",
            json=payload,
        )

        if body is None:
            return {}

        if isinstance(body, dict):
            return body

        return {"data": body}


@lru_cache(maxsize=1)
def get_supabase_rest_client() -> SupabaseRestClient:
    return SupabaseRestClient()
