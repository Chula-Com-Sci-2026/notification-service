import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import settings


def make_claims(runner_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    """Build Identity's access token claims, dropping any override set to None.

    Args:
        runner_id (uuid.UUID): Runner to name in the subject.
        **overrides (Any): Claims to replace, or None to remove one.

    Returns:
        dict[str, Any]: The claims to sign.
    """
    now = datetime.now(UTC)
    claims = {
        "sub": str(runner_id),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    } | overrides
    return {name: value for name, value in claims.items() if value is not None}


def make_token(
    runner_id: uuid.UUID,
    *,
    key: str | None = settings.ACCESS_TOKEN_SECRET,
    algorithm: str = "HS256",
    **overrides: Any,
) -> str:
    """Sign an access token the way Identity does.

    Args:
        runner_id (uuid.UUID): Runner to name in the subject.
        key (str | None, optional): Signing key. Defaults to the configured
            secret.
        algorithm (str, optional): Signing algorithm. Defaults to "HS256".
        **overrides (Any): Claims to replace, or None to remove one.

    Returns:
        str: The encoded token.
    """
    return jwt.encode(make_claims(runner_id, **overrides), key, algorithm=algorithm)


def auth_headers(runner_id: uuid.UUID) -> dict[str, str]:
    """Build request headers for an authenticated runner.

    Args:
        runner_id (uuid.UUID): Runner to authenticate as.

    Returns:
        dict[str, str]: Headers carrying a valid bearer token.
    """
    return {"Authorization": f"Bearer {make_token(runner_id)}"}
