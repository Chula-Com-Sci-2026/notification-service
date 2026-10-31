import sentry_sdk
from fastapi import FastAPI

from app.api.main import api_router, root_router
from app.core.config import settings

if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

app.include_router(root_router)
app.include_router(api_router, prefix=settings.API_V1_STR)
