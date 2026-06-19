from fastapi import APIRouter

from app.api.routes import auth, documents, health, payments
from app.api.routes.wallet import router as wallet_router
from app.api.routes.account import router as account_router
from app.api.registration import (
    router as registration_router,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(payments.router)
api_router.include_router(wallet_router)
api_router.include_router(account_router)
api_router.include_router(registration_router)