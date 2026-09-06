from typing import Any, Dict, Optional
from fastapi import status


class AppException(Exception):
    """Base exception class for all custom application exceptions."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_ERROR",
        details: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details is not None:
            result["details"] = self.details
        return {"error": result}


class NotFoundError(AppException):
    def __init__(self, resource: str, identifier: Any, message: Optional[str] = None):
        msg = message or f"{resource} with identifier '{identifier}' was not found."
        super().__init__(
            message=msg,
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            details={"resource": resource, "identifier": str(identifier)},
        )


class AuthenticationError(AppException):
    def __init__(self, message: str = "Could not validate credentials", code: str = "UNAUTHORIZED"):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=code,
        )


class PermissionDeniedError(AppException):
    def __init__(self, message: str = "You do not have permission to access this resource"):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="PERMISSION_DENIED",
        )


class ConflictError(AppException):
    def __init__(self, message: str, code: str = "CONFLICT", details: Optional[Any] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            details=details,
        )


class QuotaExceededError(AppException):
    def __init__(self, used_bytes: int, quota_bytes: int, requested_bytes: int):
        message = (
            f"Storage quota exceeded. Used: {used_bytes} bytes, "
            f"Quota: {quota_bytes} bytes, Attempted to upload: {requested_bytes} bytes."
        )
        super().__init__(
            message=message,
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            code="QUOTA_EXCEEDED",
            details={
                "storage_used_bytes": used_bytes,
                "storage_quota_bytes": quota_bytes,
                "requested_bytes": requested_bytes,
            },
        )


class StorageServiceError(AppException):
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="STORAGE_SERVICE_ERROR",
            details=details,
        )


class ValidationError(AppException):
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            details=details,
        )

