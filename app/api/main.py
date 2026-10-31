from fastapi import APIRouter

from app.api.routes import notifications, preferences, utils

# The contract serves health at the root, outside the versioned prefix.
root_router = APIRouter()
root_router.include_router(utils.router)

api_router = APIRouter()
api_router.include_router(notifications.router)
api_router.include_router(preferences.router)
