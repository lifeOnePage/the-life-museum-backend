from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    ok: bool
    code: int
    message: str
    data: T | None = None


def success_response(data=None, message: str = "Success", code: int = 200) -> ApiResponse:
    return ApiResponse(ok=True, code=code, message=message, data=data)


def error_response(message: str = "Error", code: int = 400, data=None) -> ApiResponse:
    return ApiResponse(ok=False, code=code, message=message, data=data)
