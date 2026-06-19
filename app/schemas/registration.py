from __future__ import annotations

import re

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class RegisterRequest(BaseModel):
    email: EmailStr

    password: SecretStr
    confirm_password: SecretStr

    captcha_token: str = Field(
        min_length=20,
        max_length=4096,
    )

    accepted_terms: bool

    @field_validator("captcha_token")
    @classmethod
    def validate_captcha_token(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "Vui lòng hoàn thành xác minh bảo mật."
            )

        return normalized

    @model_validator(mode="after")
    def validate_registration(self) -> "RegisterRequest":
        password = self.password.get_secret_value()
        confirm_password = (
            self.confirm_password.get_secret_value()
        )

        if len(password) < 8:
            raise ValueError(
                "Mật khẩu phải có ít nhất 8 ký tự."
            )

        if len(password) > 72:
            raise ValueError(
                "Mật khẩu không được vượt quá 72 ký tự."
            )

        if not re.search(r"[a-z]", password):
            raise ValueError(
                "Mật khẩu phải có ít nhất một chữ thường."
            )

        if not re.search(r"[A-Z]", password):
            raise ValueError(
                "Mật khẩu phải có ít nhất một chữ hoa."
            )

        if not re.search(r"[0-9]", password):
            raise ValueError(
                "Mật khẩu phải có ít nhất một chữ số."
            )

        if password != confirm_password:
            raise ValueError(
                "Mật khẩu nhập lại không khớp."
            )

        if not self.accepted_terms:
            raise ValueError(
                "Bạn cần đồng ý với điều khoản bảo mật."
            )

        return self


class RegisterResponse(BaseModel):
    message: str
    requires_email_confirmation: bool = True