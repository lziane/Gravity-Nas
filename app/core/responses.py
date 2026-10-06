from fastapi.responses import JSONResponse
from typing import Any

class ApiResponse:
    """
    Standardized response utility for GravityNAS API.
    Ensures consistent data structure for frontend integration.
    """
    @staticmethod
    def success(data: Any = None, message: str = "Success") -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "data": data,
                "message": message
            }
        )

    @staticmethod
    def error(message: str, code: str = "ERROR", status_code: int = 400) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "error",
                "error": {
                    "code": code,
                    "message": message
                }
            }
        )

    @staticmethod
    def unauthorized(message: str = "Unauthorized") -> JSONResponse:
        return ApiResponse.error(message, code="UNAUTHORIZED", status_code=401)

    @staticmethod
    def forbidden(message: str = "Forbidden") -> JSONResponse:
        return ApiResponse.error(message, code="FORBIDDEN", status_code=403)
