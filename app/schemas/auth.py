from pydantic import BaseModel


class CurrentUser(BaseModel):
    user_id: str
    email: str | None = None
    role: str | None = None


class MeResponse(BaseModel):
    user_id: str
    email: str | None = None
