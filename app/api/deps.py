import uuid
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from jwt.exceptions import InvalidTokenError
from sqlmodel import Session

from app.core import security
from app.core.db import engine


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


def get_current_runner_id(authorization: Annotated[str, Header()] = "") -> uuid.UUID:
    """Return the runner ID from the request's bearer token.

    Args:
        authorization (str, optional): `Authorization` header value. The
            empty default lets a missing header get a 401, not a 422.
            Defaults to "".

    Returns:
        uuid.UUID: The authenticated runner's ID.

    Raises:
        HTTPException: 401 if the token is missing or fails verification.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        try:
            return security.decode_runner_id(token)
        except InvalidTokenError, ValueError:
            pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentRunnerId = Annotated[uuid.UUID, Depends(get_current_runner_id)]
