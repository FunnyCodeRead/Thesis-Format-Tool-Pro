from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.db.supabase_client import (
    SupabaseAPIError,
    get_supabase_rest_client,
)
from app.schemas.account import (
    AccountProfileResponse,
    AccountProfileUpdateRequest,
)
from app.schemas.auth import CurrentUser
from app.services.accounts import (
    get_or_create_profile,
    update_profile,
)

router = APIRouter(
    prefix="/api/v1/account",
    tags=["account"],
)


@router.get(
    "/profile",
    response_model=AccountProfileResponse,
)
def read_account_profile(
    current_user: CurrentUser = Depends(get_current_user),
) -> AccountProfileResponse:
    try:
        supabase = get_supabase_rest_client()

        profile = get_or_create_profile(
            supabase,
            user_id=current_user.user_id,
            email=current_user.email,
        )

        return _to_response(profile, current_user)

    except SupabaseAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc


@router.put(
    "/profile",
    response_model=AccountProfileResponse,
)
def update_account_profile(
    body: AccountProfileUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> AccountProfileResponse:
    try:
        supabase = get_supabase_rest_client()

        get_or_create_profile(
            supabase,
            user_id=current_user.user_id,
            email=current_user.email,
        )

        profile = update_profile(
            supabase,
            user_id=current_user.user_id,
            full_name=body.full_name,
            phone=body.phone,
        )

        return _to_response(profile, current_user)

    except SupabaseAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc


def _to_response(
    profile: dict[str, Any],
    current_user: CurrentUser,
) -> AccountProfileResponse:
    return AccountProfileResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        full_name=str(profile.get("full_name") or ""),
        phone=str(profile.get("phone") or ""),
        avatar_url=profile.get("avatar_url"),
        plan=str(profile.get("plan") or "free"),
    )