"""Gateway command for nanobot CLI."""

import asyncio

import typer

from nanobot import __logo__
from nanobot.cli.app import app, console


def _create_provider(config):
    """Create LLM provider from config."""
    from nanobot.providers.litellm_provider import LiteLLMProvider
    
    api_key = config.provider.api_key
    api_base = config.provider.api_base

    if not api_key:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under provider.apiKey")
        raise typer.Exit(1)
    
    return LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )


def _create_cron_service(config, agent, bus):
    """Create and configure cron service."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}"
        )
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "whatsapp",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    
    cron.on_job = on_cron_job
    return cron


def _create_heartbeat(config, provider, model, agent, bus):
    """Create and configure heartbeat service."""
    from nanobot.heartbeat.service import HeartbeatService
    
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")
    
    async def on_heartbeat_notify(response: str) -> None:
        from nanobot.bus.events import OutboundMessage
        await bus.publish_outbound(OutboundMessage(
            channel=config.channels.notify_channel,
            chat_id=config.channels.notify_chat_id,
            content=response
        ))

    return HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=model,
        on_execute=on_heartbeat,
        on_notify=on_heartbeat_notify,
        interval_s=30 * 60,
        enabled=True
    )


async def _run_gateway(agent, channels, cron, heartbeat):
    """Run gateway main loop."""
    try:
        await cron.start()
        await heartbeat.start()
        await asyncio.gather(
            agent.run(),
            channels.start_all(agent),
        )
    except KeyboardInterrupt:
        console.print("\nShutting down...")
        heartbeat.stop()
        cron.stop()
        agent.stop()
        await channels.stop_all()


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    config = load_config()
    bus = MessageBus()
    provider = _create_provider(config)
    model = config.agents.defaults.model
    
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        exec_config=config.tools.exec,
        cron_service=cron,
        tool_logging_config=config.tools.logging,
    )
    
    cron.on_job = lambda job: agent.process_direct(
        job.payload.message, session_key=f"cron:{job.id}"
    )
    
    heartbeat = _create_heartbeat(config, provider, model, agent, bus)
    channels = ChannelManager(config, bus)
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every 30m")
    
    asyncio.run(_run_gateway(agent, channels, cron, heartbeat))