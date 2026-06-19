from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    user_id: str
    balance_vnd: int
    currency: str = "VND"
    last_updated_at: str | None = None


class TopupRequest(BaseModel):
    amount: int = Field(ge=10000)
    return_to: str | None = None


class TopupCheckoutResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    checkout_url: str
    qr_code: str | None = None
    provider_order_code: str
    expires_at: str


class TopupStatusResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    status: str
    provider_order_code: str
    paid_at: str | None = None
    balance_vnd: int
