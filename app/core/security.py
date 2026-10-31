import uuid

import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def decode_runner_id(token: str) -> uuid.UUID:
    """Verify an Identity access token and return its runner ID.

    Args:
        token (str): Encoded JWT, without the `Bearer` prefix.

    Returns:
        uuid.UUID: The runner named by the token's subject.

    Raises:
        jwt.InvalidTokenError: If the signature, the algorithm or a
            required claim fails verification.
        ValueError: If the subject is not a UUID.
    """
    claims = jwt.decode(
        token,
        settings.ACCESS_TOKEN_SECRET,
        algorithms=[ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )
    return uuid.UUID(claims["sub"])
