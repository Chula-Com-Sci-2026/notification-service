from fastapi import APIRouter

router = APIRouter(tags=["utils"])


@router.get("/up")
async def health() -> dict[str, str]:
    """Report that the process is alive."""
    return {"status": "ok"}
