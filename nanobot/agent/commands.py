"""Command registry with decorator-based registration."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CommandContext:
    """Command execution context."""
    sessions: Any
    tool_logger: Any
    workspace: Any
    model: str
    session_key: str
    channel: str
    chat_id: str
    raw_content: str = ""
    temperature: float = 0.0
    tools: list[str] = field(default_factory=list)
    message_count: int = 0
    created_at: str = ""
    memory_content: str = ""
    set_model: Callable[[str], None] = lambda m: None
    set_temp: Callable[[float], None] = lambda t: None
    clear_session: Callable[[], None] = lambda: None


class CommandRegistry:
    """Registry for commands with decorator support."""

    def __init__(self):
        self._commands: dict[str, Callable] = {}
        self._descriptions: dict[str, str] = {}

    def command(self, name: str = None, desc: str = ""):
        """Decorator to register a command.

        Usage:
            @command
            def help(ctx):
                return "Show help"

            @command("status", desc="Show status")
            def show_status(ctx):
                return "OK"
        """
        def decorator(func):
            cmd_name = f"/{name or func.__name__}"
            self._commands[cmd_name] = func
            self._descriptions[cmd_name] = desc or (func.__doc__ or "").strip()
            return func

        if callable(name):
            func = name
            name = None
            return decorator(func)
        
        return decorator

    async def execute(self, cmd_name: str, ctx: CommandContext) -> str:
        """Execute a command. Returns list of commands if not found."""
        if cmd_name not in self._commands:
            return self._list_commands()
        result = self._commands[cmd_name](ctx)
        if hasattr(result, '__await__'):
            return await result
        return result

    def _list_commands(self) -> str:
        """List all available commands."""
        lines = ["Available commands:"]
        for cmd in sorted(self._commands.keys()):
            desc = self._descriptions.get(cmd, "")
            if desc:
                lines.append(f"  {cmd:<12} {desc}")
            else:
                lines.append(f"  {cmd}")
        return "\n".join(lines)


registry = CommandRegistry()
command = registry.command


@command(desc="Restart current session")
async def restart(ctx: CommandContext) -> str:
    """Restart the session by renaming and clearing it."""
    renamed = ctx.sessions.rename_with_timestamp(ctx.session_key)
    ctx.sessions.get_or_create(ctx.session_key).clear()
    renamed2 = ctx.tool_logger.rename_with_timestamp(ctx.channel, ctx.chat_id)
    return f"Session restarted. Log: {renamed or 'none'}, Tools: {renamed2 or 'none'}"


@command(desc="Show current config")
async def config(ctx: CommandContext) -> str:
    """Show current configuration."""
    return f"config:\n  model: {ctx.model}\n  temperature: {ctx.temperature}"


@command(desc="Show available commands")
async def help(ctx: CommandContext) -> str:
    """Show all available commands."""
    return registry._list_commands()


@command(desc="Clear session history")
async def clear(ctx: CommandContext) -> str:
    """Clear the current session history."""
    ctx.clear_session()
    return "Session history cleared."


@command(desc="Show or switch model")
async def model(ctx: CommandContext) -> str:
    """Show or switch the current model."""
    parts = ctx.raw_content.split(maxsplit=1)
    if len(parts) > 1:
        new_model = parts[1].strip()
        ctx.set_model(new_model)
        return f"Model changed to: {new_model}"
    return f"Current model: {ctx.model}"


@command(desc="Show or set temperature")
async def temp(ctx: CommandContext) -> str:
    """Show or set the temperature."""
    parts = ctx.raw_content.split(maxsplit=1)
    if len(parts) > 1:
        try:
            new_temp = float(parts[1].strip())
            ctx.set_temp(new_temp)
            return f"Temperature set to: {new_temp}"
        except ValueError:
            return f"Invalid temperature value: {parts[1]}"
    return f"Current temperature: {ctx.temperature}"


@command(desc="Show today's memory")
async def memory(ctx: CommandContext) -> str:
    """Show today's memory content."""
    if ctx.memory_content:
        return f"Today's memory:\n\n{ctx.memory_content}"
    return "No memory entries for today."


@command(desc="List available tools")
async def tools(ctx: CommandContext) -> str:
    """List all available tools."""
    if not ctx.tools:
        return "No tools registered."
    tool_list = "\n".join(f"  - {tool}" for tool in sorted(ctx.tools))
    return f"Available tools:\n{tool_list}"


@command(desc="Show session history info")
async def history(ctx: CommandContext) -> str:
    """Show session history information."""
    lines = [
        f"Session: {ctx.session_key}",
        f"Messages: {ctx.message_count}",
    ]
    if ctx.created_at:
        lines.append(f"Created: {ctx.created_at}")
    return "\n".join(lines)