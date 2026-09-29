"""Open CORS for /api/public/* only.

The enquiry form's JSON endpoint is called from customers' own websites,
whose origins can't be known in advance. It needs no cookies or tokens, so
any origin may call it — but only it: the rest of the API keeps the strict
allow-list in main.py. This middleware sits outside that one.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIX = "/api/public/"


class PublicCORSMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": [
                    (b"access-control-allow-origin", b"*"),
                    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                    (b"access-control-allow-headers", b"content-type"),
                    (b"access-control-max-age", b"600"),
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_open(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", [])
                    if not k.lower().startswith(b"access-control-")
                ]
                headers.append((b"access-control-allow-origin", b"*"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_open)
