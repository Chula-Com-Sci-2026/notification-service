from fastapi import APIRouter

from app.api.routes import utils

# The contract serves health at the root, outside the versioned prefix.
root_router = APIRouter()
root_router.include_router(utils.router)

api_router = APIRouter()
