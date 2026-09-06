from typing import Annotated
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.queue_service import QueueService, get_queue_service
from app.storage import get_storage_backend
from app.storage.base import StorageBackend

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/form"
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate JWT token and return authenticated User."""
    payload = decode_access_token(token)
    user_id: str = payload.get("sub", "")
    if not user_id:
        raise AuthenticationError(message="Could not validate credentials")

    try:
        user = await AuthService.get_by_id(db, user_id)
    except Exception:
        raise AuthenticationError(message="User not found")

    if not user.is_active:
        raise AuthenticationError(message="User account is deactivated")

    return user


async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Validate current user has superuser privileges."""
    if not current_user.is_superuser:
        raise PermissionDeniedError("The user doesn't have enough privileges")
    return current_user


# Type aliases for clean FastAPI dependency injection
SessionDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
CurrentSuperuserDep = Annotated[User, Depends(get_current_active_superuser)]
StorageDep = Annotated[StorageBackend, Depends(get_storage_backend)]
QueueDep = Annotated[QueueService, Depends(get_queue_service)]

