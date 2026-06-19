from __future__ import annotations

from typing import Any

from app.db.supabase_client import SupabaseRestClient


PROFILE_COLUMNS = (
    "id,email,full_name,phone,avatar_url,"
    "plan,free_checks_used,free_checks_limit,"
    "created_at,updated_at"
)


def get_or_create_profile(
    supabase: SupabaseRestClient,
    *,
    user_id: str,
    email: str | None,
) -> dict[str, Any]:
    profile = supabase.select_one(
        "profiles",
        filters={"id": user_id},
        columns=PROFILE_COLUMNS,
    )

    if profile is None:
        default_full_name = _build_default_full_name(email, user_id)

        inserted = supabase.insert_one_if_absent(
            "profiles",
            payload={
                "id": user_id,
                "email": email,
                "full_name": default_full_name,
                "phone": "",
                "plan": "free",
                "free_checks_used": 0,
            },
            on_conflict="id",
            columns=PROFILE_COLUMNS,
        )

        if inserted is not None:
            return inserted

        profile = supabase.select_one(
            "profiles",
            filters={"id": user_id},
            columns=PROFILE_COLUMNS,
        )

        if profile is None:
            raise RuntimeError("Không thể tạo hồ sơ người dùng.")

    updates: dict[str, Any] = {}

    if not profile.get("email") and email:
        updates["email"] = email

    if not profile.get("full_name"):
        updates["full_name"] = _build_default_full_name(
            email,
            user_id,
        )

    if profile.get("phone") is None:
        updates["phone"] = ""

    if updates:
        profile = supabase.update_one(
            "profiles",
            filters={"id": user_id},
            payload=updates,
            columns=PROFILE_COLUMNS,
        )

    return profile


def update_profile(
    supabase: SupabaseRestClient,
    *,
    user_id: str,
    full_name: str,
    phone: str,
) -> dict[str, Any]:
    return supabase.update_one(
        "profiles",
        filters={"id": user_id},
        payload={
            "full_name": full_name.strip(),
            "phone": phone.strip(),
        },
        columns=PROFILE_COLUMNS,
    )


def _build_default_full_name(
    email: str | None,
    user_id: str,
) -> str:
    if email and "@" in email:
        email_name = email.split("@", 1)[0].strip()

        if email_name:
            return email_name

    return f"user_{user_id[:8]}"