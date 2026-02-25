"""Tool usage logging and notification."""

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import shutil
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import OutboundMessage


logger = logging.getLogger(__name__)


@dataclass
class ToolUsage:
    """Single tool usage record."""
    tool_name: str                    # Tool name
    parameters: dict[str, Any]       # Input parameters (sanitized)
    result: str                      # Execution result (may be truncated)
    timestamp: datetime              # Execution timestamp
    session_key: str                 # Session identifier "channel:chat_id"
    duration_ms: Optional[float] = None  # Execution duration in milliseconds
    success: bool = True             # Whether execution succeeded
    error: Optional[str] = None      # Error message if failed
    metadata: dict[str, Any] = field(default_factory=dict)  # Extended metadata

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO format string
        data["timestamp"] = self.timestamp.isoformat()
        return data


class ToolLogger:
    """Tool usage logger for recording tool executions and sending notifications."""

    def __init__(self, config, workspace: Path, bus: MessageBus):
        """
        Initialize tool logger.

        Args:
            config: Tool logging configuration
            workspace: Workspace path
            bus: Message bus for sending notifications
        """
        self.config = config
        self.workspace = workspace
        self.bus = bus
        # Sessions directory is at ~/.nanobot/sessions/
        self.sessions_dir = workspace.parent / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_parameters(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Sanitize sensitive parameters to prevent leaks.

        Args:
            tool_name: Name of the tool
            params: Original parameters

        Returns:
            Sanitized parameters with sensitive values redacted
        """
        if not self.config.sanitize_parameters:
            return params.copy()

        sanitized = params.copy()
        for key in sanitized:
            if key in self.config.parameter_blacklist:
                sanitized[key] = "[REDACTED]"
            elif isinstance(sanitized[key], str) and any(
                sensitive in key.lower() for sensitive in ["key", "pass", "token", "secret"]
            ):
                sanitized[key] = "[REDACTED]"

        return sanitized

    def rename_with_timestamp(self, channel: str, chat_id: str) -> str | None:
        """
        Rename the tools session file with a timestamp suffix.

        Args:
            channel: Channel identifier (e.g., "telegram", "whatsapp")
            chat_id: Chat identifier

        """
        path = self._get_log_file_path(channel, chat_id)
        if not path.exists():
            return None

        # Generate timestamp suffix
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        # Extract stem and suffix
        stem = path.stem
        suffix = path.suffix
        # New filename: stem-$timestamp.$suffix
        new_name = f"{stem}-{timestamp}{suffix}"
        new_path = path.parent / new_name

        # Move file
        shutil.move(str(path), str(new_path))

        # Remove from cache

        logger.info(f"Renamed tools session file: {path.name} -> {new_path.name}")
        return str(new_path)

    def _get_log_file_path(self, channel: str, chat_id: str) -> Path:
        """
        Get path to tool log file for a specific chat.

        Args:
            channel: Channel identifier (e.g., "telegram", "whatsapp")
            chat_id: Chat identifier

        Returns:
            Path to log file
        """
        # Use same safe filename logic as session manager
        safe_key = f"{channel}:{chat_id}".replace(":", "_")
        filename = f"{self.config.log_file_prefix}{safe_key}.jsonl"
        return self.sessions_dir / filename

    async def _write_to_logfile(self, usage: ToolUsage, channel: str, chat_id: str) -> None:
        """
        Write tool usage record to JSONL log file.

        Args:
            usage: Tool usage record
            channel: Channel identifier
            chat_id: Chat identifier
        """
        if not self.config.enabled:
            return

        if usage.tool_name in self.config.exclude_tools:
            return

        log_file = self._get_log_file_path(channel, chat_id)
        try:
            # Truncate result if too long
            if len(usage.result) > self.config.max_result_length:
                usage.result = usage.result[:self.config.max_result_length] + \
                f"... {len(usage.result) - self.config.max_result_length}[truncated]"

            record = usage.to_dict()
            line = json.dumps(record, ensure_ascii=False)

            # Async file write
            async with asyncio.Lock():
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

            logger.debug(f"Logged tool usage: {usage.tool_name} to {log_file}")
        except Exception as e:
            logger.error(f"Failed to write tool usage log: {e}")

    def _format_notification(self, usage: ToolUsage) -> str:
        """
        Format tool usage notification for channel.

        Args:
            usage: Tool usage record

        Returns:
            Formatted notification message
        """
        # Sanitize parameters for display
        params_display = json.dumps(usage.parameters, ensure_ascii=False)
        if len(params_display) > 200:
            params_display = params_display[:200] + "..."

        status_emoji = "✅" if usage.success else "❌"
        result_preview = usage.result
        if len(result_preview) > 100:
            result_preview = result_preview[:100] + "..."

        lines = [
            f"🛠️ 工具执行: {usage.tool_name}",
            f"📁 参数: {params_display}",
            f"{status_emoji} 结果: {result_preview}",
        ]

        if usage.duration_ms:
            lines.append(f"⏱️ 耗时: {usage.duration_ms:.0f}ms")

        if usage.error:
            lines.append(f"⚠️ 错误: {usage.error}")

        return "\n".join(lines)

    async def _send_to_channel(self, usage: ToolUsage, channel: str, chat_id: str) -> None:
        """
        Send tool usage notification to channel.

        Args:
            usage: Tool usage record
            channel: Channel identifier
            chat_id: Chat identifier
        """
        if not self.config.notify_channel:
            return

        if usage.tool_name in self.config.exclude_tools:
            return

        try:
            notification = ''
            if not self.config.typing_only:
                notification = self._format_notification(usage)
            outbound_msg = OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=notification
            )
            await self.bus.publish_outbound(outbound_msg)
            logger.debug(f"Sent tool notification for {usage.tool_name} to {channel}:{chat_id}")
        except Exception as e:
            logger.error(f"Failed to send tool notification: {e}")

    async def log_tool_usage(self, usage: ToolUsage, channel: str, chat_id: str) -> None:
        """
        Log tool usage and optionally send notification.

        This method runs logging and notification as background tasks
        to avoid blocking the main tool execution flow.

        Args:
            usage: Tool usage record
            channel: Channel identifier
            chat_id: Chat identifier
        """
        if not self.config.enabled:
            return

        # Run logging and notification in background
        asyncio.create_task(self._write_to_logfile(usage, channel, chat_id))

        if self.config.notify_channel:
            asyncio.create_task(self._send_to_channel(usage, channel, chat_id))