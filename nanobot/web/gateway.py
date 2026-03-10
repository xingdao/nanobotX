"""Web gateway for nanobot task submission."""

import base64
from pathlib import Path
from functools import wraps

from aiohttp import web
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.utils.deploy import Deploy

TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_template(name: str) -> str:
    """Load HTML template from file."""
    template_path = TEMPLATES_DIR / name
    return template_path.read_text(encoding="utf-8")


def auth_required(handler):
    """Decorator to check authentication for a request handler."""
    @wraps(handler)
    async def wrapper(self, request: web.Request) -> web.Response:
        # 1. 优先获取 Cloudflare 提供的真实 IP
        client_ip = request.headers.get("CF-Connecting-IP")
        # 2. 如果没有（可能未走 CF），则回退到默认远程地址
        if not client_ip:
            logger.info(f"[WebGateway] remote ip: {client_ip}")
            client_ip = request.remote
        else:
            logger.info(f"[WebGateway] cf ip: {client_ip}")
        
        if client_ip != self._authenticated_ip:
            auth = request.headers.get("Authorization")
            if not self._check_auth(auth):
                return web.Response(
                    status=401,
                    headers={"WWW-Authenticate": 'Basic realm="nanobot"'},
                )
            self._authenticated_ip = client_ip
        return await handler(self, request)
    return wrapper


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

        # Preload templates
        self._templates = {
            "index": load_template("index.html"),
            "deploy": load_template("deploy.html"),
            "result": load_template("result.html"),
        }

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

    def _render_template(self, name: str, **kwargs) -> str:
        """Render a template with variable substitution."""
        template = self._templates[name]
        result = template
        for key, value in kwargs.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result
    
    @auth_required
    async def handle_index(self, request: web.Request) -> web.Response:
        return web.Response(
            text=self._templates["index"],
            content_type="text/html"
        )

    @auth_required
    async def handle_task(self, request: web.Request) -> web.Response:
        try:
            data = await request.post()
            task = data.get("task", "")
            if not task or not isinstance(task, str):
                return web.Response(text="Task is required", status=400)

            task = task.strip()
            if not task:
                return web.Response(text="Task cannot be empty", status=400)

            # Log non-read operation
            logger.info(f"[WebGateway] Task submitted: {task[:100]}...")

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
            logger.error(f"[WebGateway] Task error: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    @auth_required
    async def handle_deploy_page(self, request: web.Request) -> web.Response:
        return web.Response(
            text=self._templates["deploy"],
            content_type="text/html"
        )

    @auth_required
    async def handle_deploy_restart(self, request: web.Request) -> web.Response:
        try:
            cmd = "docker restart nanobot-gateway-1"
            logger.info(f"[WebGateway] Restart requested: {cmd}")

            deploy = Deploy()
            result = await deploy.execute(cmd)

            logger.info(f"[WebGateway] Restart result: {result[:200]}...")

            html = self._render_template(
                "result",
                title="Restart Executed",
                result=result,
                back_url="/deploy",
                back_text="Back to Deploy"
            )
            return web.Response(text=html, content_type="text/html")
        except Exception as e:
            logger.error(f"[WebGateway] Restart error: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    @auth_required
    async def handle_deploy_apply(self, request: web.Request) -> web.Response:
        try:
            # Parse multipart form data
            reader = await request.multipart()
            patch_content = None

            async for field in reader:
                if field.name == "patch":
                    patch_content = await field.read()
                    break

            if not patch_content:
                return web.Response(text="No patch file uploaded", status=400)

            # Save patch file
            patch_dir = Path.home() / ".nanobot"
            patch_dir.mkdir(parents=True, exist_ok=True)
            patch_path = patch_dir / "uploaded.patch"
            patch_path.write_bytes(patch_content)

            logger.info(f"[WebGateway] Patch uploaded: {patch_path} ({len(patch_content)} bytes)")

            # Execute deploy commands
            deploy = Deploy()
            commands = [
                "cd /root/.local/share/uv/tools/nanobot-ai/lib/python3.12/site-packages/nanobot && git restore --staged .",
                f"git apply --unsafe-paths -p1 --directory=/root/.local/share/uv/tools/nanobot-ai/lib/python3.12/site-packages/ {patch_path}",
                "docker restart nanobot-gateway-1"
            ]

            results = []
            for cmd in commands:
                logger.info(f"[WebGateway] Executing: {cmd}")
                result = await deploy.execute(cmd)
                results.append(f"$ {cmd}\n{result}")

            logger.info(f"[WebGateway] Deploy completed")

            html = self._render_template(
                "result",
                title="Deploy Executed",
                result="\n".join(results),
                back_url="/deploy",
                back_text="Back to Deploy"
            )
            return web.Response(text=html, content_type="text/html")
        except Exception as e:
            logger.error(f"[WebGateway] Deploy error: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self.handle_index)
        self._app.router.add_post("/task", self.handle_task)
        self._app.router.add_get("/deploy", self.handle_deploy_page)
        self._app.router.add_post("/deploy/restart", self.handle_deploy_restart)
        self._app.router.add_post("/deploy/apply", self.handle_deploy_apply)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None