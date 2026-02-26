"""Status command for nanobot CLI."""

import typer

from nanobot import __logo__
from nanobot.cli.app import app, console


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        console.print(f"Model: {config.agents.defaults.model}")
        
        has_api_key = bool(config.provider.api_key)
        console.print(f"API Key: {'[green]✓[/green]' if has_api_key else '[dim]not set[/dim]'}")
        if config.provider.api_base:
            console.print(f"API Base: [green]✓ {config.provider.api_base}[/green]")