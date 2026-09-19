from fastapi import Header, HTTPException

from .config import settings


def require_token(authorization: str = Header(default="")):
    if authorization != f"Bearer {settings.world_api_token}":
        raise HTTPException(401, "missing or invalid bearer token")
