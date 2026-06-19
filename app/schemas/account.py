from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class AccountProfileResponse(BaseModel):
    user_id: str
    email: str | None = None
    full_name: str
    phone: str
    avatar_url: str | None = None
    plan: str = "free"


class AccountProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(default="", max_length=20)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())

        if len(normalized) < 2:
            raise ValueError("Họ và tên phải có ít nhất 2 ký tự.")

        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = re.sub(r"[\s()-]", "", value.strip())

        if not normalized:
            return ""

        if not re.fullmatch(r"(?:0|\+84)\d{9,10}", normalized):
            raise ValueError("Số điện thoại không hợp lệ.")

        return normalized