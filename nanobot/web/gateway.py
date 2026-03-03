"""Web gateway for nanobot task submission."""

import base64

from aiohttp import web

from nanobot.bus.events import InboundMessage, OutboundMessage


class WebGateway:
    def __init__(
        self,
        web_config,
        bus,
        notify_channel: str,
        notify_chat_id: str,
        port: int,
    ):
        self.web_config = web_config
        self.bus = bus
        self.notify_channel = notify_channel
        self.notify_chat_id = notify_chat_id
        self.port = port
        self._authenticated_ip: str | None = None
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def _check_auth(self, auth_header: str | None) -> bool:
        if not auth_header:
            return False
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            if ":" not in decoded:
                return False
            username, password = decoded.split(":", 1)
            return (
                username == self.web_config.username
                and password == self.web_config.password
            )
        except Exception:
            return False

    async def handle_index(self, request: web.Request) -> web.Response:
        html = """<!DOCTYPE html>
<html>
<head><title>Nanobot Task</title></head>
<body>
  <h1>Submit Task</h1>
  <form method="POST" action="/task">
    <textarea name="task" rows="5" cols="50" placeholder="Enter task..."></textarea><br>
    <button type="submit">Submit</button>
  </form>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")

    async def handle_task(self, request: web.Request) -> web.Response:
        client_ip = request.remote

        if client_ip == self._authenticated_ip:
            return await self._process_task(request)

        auth = request.headers.get("Authorization")
        if not self._check_auth(auth):
            return web.Response(
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="nanobot"'},
            )

        self._authenticated_ip = client_ip
        return await self._process_task(request)

    async def _process_task(self, request: web.Request) -> web.Response:
        try:
            data = await request.post()
            task = data.get("task", "")
            if not task or not isinstance(task, str):
                return web.Response(text="Task is required", status=400)

            task = task.strip()
            if not task:
                return web.Response(text="Task cannot be empty", status=400)

            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=self.notify_channel,
                    chat_id=self.notify_chat_id,
                    content=f"Received task: {task}",
                )
            )

            await self.bus.publish_inbound(
                InboundMessage(
                    channel=self.notify_channel,
                    sender_id=self.notify_chat_id,
                    chat_id=self.notify_chat_id,
                    content=task,
                )
            )

            return web.Response(text="Task submitted")
        except Exception as e:
            return web.Response(text=f"Error: {e}", status=500)

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self.handle_index)
        self._app.router.add_post("/task", self.handle_task)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
