from fastapi import APIRouter, status

from app import crud
from app.api.deps import CurrentRunnerId, SessionDep
from app.models import ApiError, PreferencesPublic, PreferencesUpdate

router = APIRouter(
    prefix="/notifications/preferences",
    tags=["notifications"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ApiError},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiError},
    },
)


@router.get("")
def get_preferences(
    session: SessionDep, runner_id: CurrentRunnerId
) -> PreferencesPublic:
    """Return the runner's setting for every notification category."""
    return PreferencesPublic.from_choices(
        crud.list_preferences(session=session, recipient_id=runner_id)
    )


@router.patch("")
def update_preferences(
    update: PreferencesUpdate, session: SessionDep, runner_id: CurrentRunnerId
) -> PreferencesPublic:
    """Turn notification categories on or off, leaving the rest as they are."""
    crud.update_preferences(
        session=session, recipient_id=runner_id, choices=update.categories
    )
    return PreferencesPublic.from_choices(
        crud.list_preferences(session=session, recipient_id=runner_id)
    )
