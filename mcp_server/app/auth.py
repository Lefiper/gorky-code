"""Bearer authentication at the ASGI boundary; health probe stays public."""
import hmac
import os
from starlette.responses import JSONResponse


class BearerGuard:
    def __init__(self, app):
        self.app = app
        self.token = os.environ.get("MCP_AUTH_TOKEN", "")
        if not self.token:
            raise RuntimeError("MCP_AUTH_TOKEN is required for HTTP transport")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") != "/health":
            headers = dict(scope.get("headers", []))
            expected = ("Bearer " + self.token).encode()
            if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
                await JSONResponse({"error": "Unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)
