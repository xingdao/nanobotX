import pytest
from pathlib import Path

from nanobot.agent.commands import CommandRegistry, CommandContext, command


class MockSession:
    def __init__(self):
        self.cleared = False
        self.messages = []
        self.created_at = None
    
    def get_or_create(self, key):
        self.cleared = True
        return self
    
    def clear(self):
        self.cleared = True
    
    def rename_with_timestamp(self, key):
        return None


class MockToolLogger:
    def rename_with_timestamp(self, channel, chat_id):
        return None


@pytest.fixture
def ctx():
    return CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
    )


@pytest.fixture
def ctx_with_params():
    return CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        raw_content="/model gpt-4o",
        temperature=0.5,
        tools=["read", "write", "exec"],
        message_count=10,
        created_at="2024-01-01T00:00:00",
        memory_content="Test memory",
    )


def test_decorator_registers_command_by_function_name():
    reg = CommandRegistry()
    
    @reg.command
    def test_cmd(ctx):
        return "test result"
    
    assert "/test_cmd" in reg._commands
    assert reg._commands["/test_cmd"](None) == "test result"


def test_decorator_registers_command_with_custom_name():
    reg = CommandRegistry()
    
    @reg.command("mycommand")
    def some_func(ctx):
        return "custom"
    
    assert "/mycommand" in reg._commands
    assert "/some_func" not in reg._commands


def test_decorator_stores_description():
    reg = CommandRegistry()
    
    @reg.command(desc="Test command description")
    def test_cmd(ctx):
        return "ok"
    
    assert reg._descriptions["/test_cmd"] == "Test command description"


def test_decorator_uses_docstring_as_description():
    reg = CommandRegistry()
    
    @reg.command
    def test_cmd(ctx):
        """This is from docstring."""
        return "ok"
    
    assert reg._descriptions["/test_cmd"] == "This is from docstring."


@pytest.mark.asyncio
async def test_execute_returns_result_for_registered_command(ctx):
    reg = CommandRegistry()
    
    @reg.command
    def hello(ctx):
        return "hello world"
    
    result = await reg.execute("/hello", ctx)
    assert result == "hello world"


@pytest.mark.asyncio
async def test_execute_supports_async_function(ctx):
    reg = CommandRegistry()
    
    @reg.command
    async def async_cmd(ctx):
        return "async result"
    
    result = await reg.execute("/async_cmd", ctx)
    assert result == "async result"


@pytest.mark.asyncio
async def test_execute_returns_command_list_for_unknown_command(ctx):
    reg = CommandRegistry()
    
    @reg.command(desc="First command")
    def cmd1(ctx):
        return "1"
    
    @reg.command(desc="Second command")
    def cmd2(ctx):
        return "2"
    
    result = await reg.execute("/unknown", ctx)
    
    assert "Available commands:" in result
    assert "/cmd1" in result
    assert "/cmd2" in result
    assert "First command" in result


@pytest.mark.asyncio
async def test_list_commands_sorted_alphabetically(ctx):
    reg = CommandRegistry()
    
    @reg.command
    def z_cmd(ctx):
        return "z"
    
    @reg.command
    def a_cmd(ctx):
        return "a"
    
    result = await reg.execute("/unknown", ctx)
    lines = result.split("\n")
    
    assert lines.index("  /a_cmd") < lines.index("  /z_cmd")


@pytest.mark.asyncio
async def test_restart_command(ctx):
    from nanobot.agent.commands import registry
    
    result = await registry.execute("/restart", ctx)
    assert "Session restarted" in result
    assert ctx.sessions.cleared is True


@pytest.mark.asyncio
async def test_config_command(ctx):
    from nanobot.agent.commands import registry
    
    result = await registry.execute("/config", ctx)
    assert "model: gpt-4" in result


@pytest.mark.asyncio
async def test_help_command(ctx):
    from nanobot.agent.commands import registry
    
    result = await registry.execute("/help", ctx)
    assert "Available commands:" in result
    assert "/restart" in result
    assert "/config" in result


@pytest.mark.asyncio
async def test_unknown_command_shows_help(ctx):
    from nanobot.agent.commands import registry
    
    result = await registry.execute("/nonexistent", ctx)
    assert "Available commands:" in result


@pytest.mark.asyncio
async def test_clear_command():
    from nanobot.agent.commands import registry
    
    session = MockSession()
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        clear_session=lambda: setattr(session, 'cleared', True),
    )
    
    result = await registry.execute("/clear", ctx)
    assert "cleared" in result.lower()


@pytest.mark.asyncio
async def test_model_command_show():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        raw_content="/model",
    )
    
    result = await registry.execute("/model", ctx)
    assert "Current model: gpt-4" in result


@pytest.mark.asyncio
async def test_model_command_switch():
    from nanobot.agent.commands import registry
    
    changed_model = None
    
    def set_model(m):
        nonlocal changed_model
        changed_model = m
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        raw_content="/model gpt-4o",
        set_model=set_model,
    )
    
    result = await registry.execute("/model", ctx)
    assert "Model changed to: gpt-4o" in result
    assert changed_model == "gpt-4o"


@pytest.mark.asyncio
async def test_temp_command_show():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        raw_content="/temp",
        temperature=0.7,
    )
    
    result = await registry.execute("/temp", ctx)
    assert "Current temperature: 0.7" in result


@pytest.mark.asyncio
async def test_temp_command_set():
    from nanobot.agent.commands import registry
    
    changed_temp = None
    
    def set_temp(t):
        nonlocal changed_temp
        changed_temp = t
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        raw_content="/temp 0.8",
        temperature=0.5,
        set_temp=set_temp,
    )
    
    result = await registry.execute("/temp", ctx)
    assert "Temperature set to: 0.8" in result
    assert changed_temp == 0.8


@pytest.mark.asyncio
async def test_temp_command_invalid():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        raw_content="/temp invalid",
        temperature=0.5,
    )
    
    result = await registry.execute("/temp", ctx)
    assert "Invalid temperature" in result


@pytest.mark.asyncio
async def test_memory_command_with_content():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        memory_content="Today I learned Python decorators.",
    )
    
    result = await registry.execute("/memory", ctx)
    assert "Today's memory" in result
    assert "Python decorators" in result


@pytest.mark.asyncio
async def test_memory_command_empty():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        memory_content="",
    )
    
    result = await registry.execute("/memory", ctx)
    assert "No memory entries" in result


@pytest.mark.asyncio
async def test_tools_command():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        tools=["read", "write", "exec"],
    )
    
    result = await registry.execute("/tools", ctx)
    assert "Available tools" in result
    assert "read" in result
    assert "write" in result


@pytest.mark.asyncio
async def test_tools_command_empty():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:123",
        channel="test",
        chat_id="123",
        tools=[],
    )
    
    result = await registry.execute("/tools", ctx)
    assert "No tools registered" in result


@pytest.mark.asyncio
async def test_history_command():
    from nanobot.agent.commands import registry
    
    ctx = CommandContext(
        sessions=MockSession(),
        tool_logger=MockToolLogger(),
        workspace=Path("/tmp"),
        model="gpt-4",
        session_key="test:456",
        channel="test",
        chat_id="456",
        message_count=25,
        created_at="2024-01-15T10:30:00",
    )
    
    result = await registry.execute("/history", ctx)
    assert "Session: test:456" in result
    assert "Messages: 25" in result
    assert "Created: 2024-01-15T10:30:00" in result