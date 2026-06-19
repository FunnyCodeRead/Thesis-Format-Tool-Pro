from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_user
from app.db.supabase_client import SupabaseAPIError, get_supabase_rest_client
from app.schemas.auth import CurrentUser
from app.schemas.wallet import (
    TopupCheckoutResponse,
    TopupRequest,
    TopupStatusResponse,
    WalletResponse,
)
from app.services.wallets import (
    create_wallet_topup,
    get_or_create_wallet,
    get_wallet_topup_status,
    wallet_response,
)
from app.services.payments.payos import PayOSError

router = APIRouter(tags=["wallet"])


@router.get("/api/v1/wallet", response_model=WalletResponse)
async def get_wallet(
    current_user: CurrentUser = Depends(get_current_user),
) -> WalletResponse:
    try:
        supabase = get_supabase_rest_client()
        wallet = get_or_create_wallet(supabase, current_user.user_id)
        return wallet_response(wallet)
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/v1/wallet/topup", response_model=TopupCheckoutResponse)
async def create_topup(
    body: TopupRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> TopupCheckoutResponse:
    try:
        supabase = get_supabase_rest_client()
        return create_wallet_topup(
            supabase,
            current_user=current_user,
            amount=int(body.amount),
            return_to=body.return_to,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except PayOSError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/api/v1/wallet/topup-status", response_model=TopupStatusResponse)
async def get_topup_status(
    order_code: str = Query(alias="orderCode"),
    current_user: CurrentUser = Depends(get_current_user),
) -> TopupStatusResponse:
    try:
        supabase = get_supabase_rest_client()
        return get_wallet_topup_status(
            supabase,
            current_user=current_user,
            provider_order_code=order_code,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except PayOSError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
