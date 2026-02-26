"""Configuration schema using Pydantic."""

from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    notify_channel: str = "telegram"
    notify_chat_id: str = ""


class AgentDefaults(BaseModel):
    """Default agent configuration."""
    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.0
    max_tool_iterations: int = 20


class AgentsConfig(BaseModel):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(BaseModel):
    """LLM provider configuration."""
    api_key: str = ""
    api_base: str | None = None


class HeartbeatConfig(BaseModel):
    """Heartbeat service configuration."""
    enabled: bool = True
    interval_s: int = 30 * 60  # 30 minutes


class GatewayConfig(BaseModel):
    """Gateway/server configuration."""
    host: str = "0.0.0.0"
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class ExecToolConfig(BaseModel):
    """Shell exec tool configuration."""
    timeout: int = 60
    restrict_to_workspace: bool = False  # If true, block commands accessing paths outside workspace


class ToolLoggingConfig(BaseModel):
    """Tool logging configuration."""
    enabled: bool = False                    # Whether tool logging is enabled
    notify_channel: bool = False             # Whether to send notifications to channel
    typing_only: bool = True                 # send typing only to channel
    log_file_prefix: str = "tools-"          # Prefix for log files
    max_result_length: int = 100            # Maximum length of result to log
    exclude_tools: list[str] = []            # Tools to exclude from logging
    sanitize_parameters: bool = True         # Whether to sanitize sensitive parameters
    parameter_blacklist: list[str] = Field(  # Sensitive parameter blacklist
        default_factory=lambda: ["api_key", "password", "token", "secret"]
    )


class ToolsConfig(BaseModel):
    """Tools configuration."""
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    logging: ToolLoggingConfig = Field(default_factory=ToolLoggingConfig)


class Config(BaseSettings):
    """Root configuration for nanobot."""
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    
    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()
    
    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
