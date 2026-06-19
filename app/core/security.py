import time
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwk, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError
import requests

from app.core.config import settings
from app.schemas.auth import CurrentUser

bearer_scheme = HTTPBearer(auto_error=False)
JWKS_CACHE_SECONDS = 300
ASYMMETRIC_ALGORITHMS = {"ES256", "RS256"}
LEGACY_ALGORITHMS = {"HS256"}

_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expires_at = 0.0


class JWTVerificationConfigError(Exception):
    pass


class JWKSFetchError(Exception):
    pass


def _auth_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _supabase_project_url() -> str:
    project_url = settings.supabase_url.strip().rstrip("/")
    for suffix in ("/rest/v1", "/auth/v1"):
        if project_url.endswith(suffix):
            return project_url[: -len(suffix)]
    return project_url


def _supabase_jwks_url() -> str:
    project_url = _supabase_project_url()
    if not project_url:
        raise JWTVerificationConfigError("SUPABASE_URL is required for JWKS verification.")
    return f"{project_url}/auth/v1/.well-known/jwks.json"


def _supabase_issuer() -> str | None:
    project_url = _supabase_project_url()
    return f"{project_url}/auth/v1" if project_url else None


def _decode_options() -> dict[str, bool]:
    return {
        "verify_aud": bool(settings.supabase_jwt_audience),
        "verify_iss": bool(_supabase_issuer()),
    }


def _decode_kwargs() -> dict[str, str]:
    kwargs: dict[str, str] = {}
    if settings.supabase_jwt_audience:
        kwargs["audience"] = settings.supabase_jwt_audience
    issuer = _supabase_issuer()
    if issuer:
        kwargs["issuer"] = issuer
    return kwargs


def _get_supabase_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_cache_expires_at

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_cache_expires_at:
        return _jwks_cache

    try:
        response = requests.get(_supabase_jwks_url(), timeout=5)
        response.raise_for_status()
        jwks = response.json()
    except requests.RequestException as exc:
        raise JWKSFetchError("Unable to fetch Supabase JWKS.") from exc
    except ValueError as exc:
        raise JWKSFetchError("Supabase JWKS response is not valid JSON.") from exc

    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise JWKSFetchError("Supabase JWKS response is malformed.")

    _jwks_cache = jwks
    _jwks_cache_expires_at = now + JWKS_CACHE_SECONDS
    return jwks


def _find_jwk_for_header(header: dict[str, Any]) -> str:
    kid = header.get("kid")
    alg = header.get("alg")

    if not isinstance(kid, str) or not kid:
        raise JWTError("Token key id is missing.")

    jwks = _get_supabase_jwks()
    for key in jwks["keys"]:
        if key.get("kid") == kid and key.get("alg") == alg:
            return jwk.construct(key, alg).to_pem().decode("utf-8")

    raise JWTError("No matching Supabase JWKS key found.")


def _decode_supabase_access_token(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")

    if alg in LEGACY_ALGORITHMS:
        if not settings.supabase_jwt_secret:
            raise JWTVerificationConfigError(
                "SUPABASE_JWT_SECRET is required for HS256 JWT verification."
            )
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[alg],
            options=_decode_options(),
            **_decode_kwargs(),
        )

    if alg in ASYMMETRIC_ALGORITHMS:
        public_key_pem = _find_jwk_for_header(header)
        return jwt.decode(
            token,
            public_key_pem,
            algorithms=[alg],
            options=_decode_options(),
            **_decode_kwargs(),
        )

    raise JWTError(f"Unsupported JWT algorithm: {alg}.")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _auth_error("Missing bearer token.")

    if not settings.supabase_url and not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase JWT verification is not configured.",
        )

    try:
        payload = _decode_supabase_access_token(credentials.credentials)
    except ExpiredSignatureError as exc:
        raise _auth_error("Token has expired.") from exc
    except JWTClaimsError as exc:
        raise _auth_error("Token claims are invalid.") from exc
    except JWTVerificationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except JWKSFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except JWTError as exc:
        raise _auth_error("Token is invalid.") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise _auth_error("Token subject is missing.")
    try:
        user_id = str(UUID(str(user_id)))
    except ValueError as exc:
        raise _auth_error("Token subject is invalid.") from exc

    return CurrentUser(
        user_id=user_id,
        email=payload.get("email"),
        role=payload.get("role"),
    )
