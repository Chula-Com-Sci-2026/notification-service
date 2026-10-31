import logging
from http import HTTPStatus

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.main import api_router, root_router
from app.core.config import settings
from app.models import ApiError

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

app.include_router(root_router)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render an HTTP error in the `code` and `message` shape.

    Args:
        _request (Request): The failed request.
        exc (StarletteHTTPException): The error raised while handling it.

    Returns:
        JSONResponse: The error body, with any headers the error set.
    """
    body = ApiError(code=HTTPStatus(exc.status_code).name, message=exc.detail)
    return JSONResponse(
        status_code=exc.status_code, content=body.model_dump(), headers=exc.headers
    )


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeoutError)
async def database_unavailable(_request: Request, exc: Exception) -> JSONResponse:
    """Answer 503 when the database cannot serve the request.

    Args:
        _request (Request): The failed request.
        exc (Exception): The database error, logged but never returned.

    Returns:
        JSONResponse: A generic 503 body.
    """
    logger.error("Database unavailable: %s", exc)
    code = status.HTTP_503_SERVICE_UNAVAILABLE
    body = ApiError(
        code=HTTPStatus(code).name, message="Notifications are unavailable right now"
    )
    return JSONResponse(status_code=code, content=body.model_dump())
