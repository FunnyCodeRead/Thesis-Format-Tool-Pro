from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser, MeResponse

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.get("/me", response_model=MeResponse)
def read_me(current_user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user_id=current_user.user_id, email=current_user.email)
