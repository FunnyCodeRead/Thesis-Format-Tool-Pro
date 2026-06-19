from pydantic import BaseModel


class CheckoutResponse(BaseModel):
    order_id: str
    document_id: str
    status: str
    amount: int
    currency: str
    provider_order_code: str
    checkout_url: str
    qr_code: str | None = None
    expires_at: str
    reused: bool = False


class PaymentStatusResponse(BaseModel):
    order_id: str
    document_id: str
    status: str
    provider_status: str | None = None
    amount: int
    currency: str
    provider_order_code: str
    checkout_url: str | None = None
    expires_at: str
    paid_at: str | None = None
    can_fix: bool
    can_download: bool
    refreshed_at: str


class PayOSWebhookResponse(BaseModel):
    status: str
    processed: bool
    provider_order_code: str | None = None
    duplicate: bool = False
    event_id: str | None = None
