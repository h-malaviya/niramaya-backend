from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

EXCLUDED_PATHS = [
    "/docs",
    "/openapi.json",
    "/login",
    "/signup",
    "/refresh-token"
]

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in EXCLUDED_PATHS):
            return await call_next(request)

        # Example: logging / audit
        print(f"Request → {request.method} {request.url.path}")

        return await call_next(request)
