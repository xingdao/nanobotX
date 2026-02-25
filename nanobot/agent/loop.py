"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, GlobTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.skill import ReadSkill, RunSkill
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.logger import ToolLogger, ToolUsage
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager
from nanobot.agent.hooks import AgentContext, trigger
from nanobot.agent.rules import register_default_rules

import xml.etree.ElementTree as ET
from nanobot.config.schema import ExecToolConfig, ToolLoggingConfig
from nanobot.cron.service import CronService

class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        tool_logging_config: "ToolLoggingConfig | None" = None,
        cron_service: "CronService | None" = None,
    ):

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.tool_logging_config = tool_logging_config or ToolLoggingConfig()

        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.tool_logger = ToolLogger(
            config=self.tool_logging_config,
            workspace=self.workspace,
            bus=self.bus
        )
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )

        register_default_rules()
        
        self._running = False
        self.abort = False
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(ReadSkill())
        self.tools.register(RunSkill())
        self.tools.register(EditFileTool())
        self.tools.register(GlobTool())
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        
        # Web tools
        # self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _build_tools_xml(self) -> str:
        """Build XML summary of available tools."""
        tools_defs = self.tools.get_definitions()
        if not tools_defs:
            return ""

        lines = []
        for tool_def in tools_defs:
            func = tool_def.get("function", {})
            name = self._escape_xml(func.get("name", "unknown"))
            description = self._escape_xml(func.get("description", ""))
            lines.append(f" <name>{name}</name>")
            lines.append(f" <description>{description}</description>")
        return "\n".join(lines)

    def _build_skills_xml(self) -> str:
        """Build XML summary of available skills."""
        # Use existing skills loader
        return self.context.skills.build_skills_summary()

    def _read_memory_content(self) -> str:
        """Read memory content from workspace."""
        memory_path = self.workspace / "memory" / "MEMORY.md"
        if not memory_path.exists():
            return ""
        return memory_path.read_text(encoding="utf-8")

    def _build_plan_prompt(self) -> str | None:
        """Build plan prompt from template."""
        plan_template_path = self.workspace / "PLAN.md"
        if not plan_template_path.exists():
            return None

        template = plan_template_path.read_text(encoding="utf-8")
        return template

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    if not msg.metadata.get('command'):
                        response = await self._process_message(msg)
                    else:
                        self.abort = False
                        response = await self._process_command(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _execute_tool_with_logging(self, tool_name: str, params: dict[str, Any],
                                       session_key: str, channel: str, chat_id: str) -> str:
        """
        Execute a tool with logging and notification.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            session_key: Session identifier "channel:chat_id"
            channel: Channel identifier
            chat_id: Chat identifier

        Returns:
            Tool execution result
        """
        from datetime import datetime

        start_time = datetime.now()
        result = await self.tools.execute(tool_name, params)
        end_time = datetime.now()

        if self.tool_logging_config.enabled:
            usage = ToolUsage(
                tool_name=tool_name,
                parameters=params,
                result=result,
                timestamp=start_time,
                session_key=session_key,
                duration_ms=round((end_time - start_time).total_seconds() * 1000, 2),
                success=not result.startswith("Error"),
                error=None if not result.startswith("Error") else result
            )
            await self.tool_logger.log_tool_usage(usage, channel, chat_id)

        return result

    async def _process_command(self, msg: InboundMessage) -> OutboundMessage | None:
        # Handle /start command
        cout_content = f"{msg.content} command not support"
        if msg.content == '/restart':
            logger.info(f"Handling /restart command for session {msg.session_key}")
            # Rename existing session file with timestamp
            renamed = self.sessions.rename_with_timestamp(msg.session_key)
            if renamed:
                logger.info(f"Renamed session file to {renamed}")
            else:
                logger.info("No existing session file to rename")
            renamed = self.tool_logger.rename_with_timestamp(msg.channel, msg.chat_id)
            if renamed:
                logger.info(f"Renamed tools session file to {renamed}")
            else:
                logger.info("No existing tools session file to rename")
            # Clear cache and get fresh session
            self.sessions.get_or_create(msg.session_key).clear()
            cout_content = f"{msg.session_key} restart ok"
        elif msg.content == '/config':
            config = dict(
                model=self.model
            )
            cout_content=f"config:\n{config}"
        return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=cout_content
            )
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        temp_max_iterations = self.max_iterations
        if msg.content.strip().startswith('好好想想'):
            temp_max_iterations = 50

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)

        # Build initial messages (use get_history for LLM-formatted messages)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
        )
        # Plan step
        tools_actions = None
        if any([x in msg.content.split('\n', 1)[0] for x in ('plan','计划')]):
            # Build messages using the same structure as default
            plan_messages = self.context.build_messages(
                history=session.get_history(),
                current_message=f"{self._build_plan_prompt()}\n\n## 用户任务\n\n{msg.content}",
                media=msg.media if msg.media else None,
            )
            # Get plan response
            plan_response = await self.provider.chat(
                messages=plan_messages,
                model='deepseek/deepseek-reasoner'
            )
            logger.info(f"Executing plan {plan_response}")
            
            # Parse XML
            try:
                # Wrap in root tag for parsing
                root = ET.fromstring(f"<root>{plan_response.content}</root>")
                clarity_elem = root.find("clarity")
                if clarity_elem is not None:
                    clarity = clarity_elem.text.lower() if clarity_elem.text else "true"
                    if clarity == "false":
                        # Return unclear points directly
                        unclear_elem = root.find("unclear_points")
                        unclear_text = unclear_elem.text if unclear_elem is not None else "The plan is unclear."
                        # Save to session
                        await self.bus.publish_outbound( OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=unclear_text
                        ))
                    # clarity is true, extract plan details
                    task_elem = root.find("task")
                    tools_actions_elem = root.find("tools_and_actions")
                    warnings_elem = root.find("warnings")

                    task = task_elem.text if task_elem is not None else ""
                    tools_actions = tools_actions_elem.text if tools_actions_elem is not None else ""
                    warnings = warnings_elem.text if warnings_elem is not None else ""

                    # Append plan details to the user message in the main messages
                    plan_addition = f"\n\n## Plan\n\n**Task:** {task}\n\n**Tools and Actions:** {tools_actions}\n\n**Warnings:** {warnings}"
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"plan_addition:{plan_addition}"
                    ))
                    # Modify the last user message in messages list
                    if messages and messages[-1]["role"] == "user":
                        messages[-1]["content"] = msg.content + plan_addition
                    else:
                        logger.warning("Cannot find user message to append plan details")
            except ET.ParseError as e:
                logger.warning(f"Failed to parse plan XML: {e}")
            except Exception as e:
                logger.warning(f"Error during plan step: {e}", exc_info=True)
        if msg.content.endswith('plan'):
            return
        # Agent loop
        final_content = None
        summary_tools = []
        ctx = AgentContext(input=msg.content)
        while ctx.loop_count < temp_max_iterations and not self.abort:

            # Hooks: before_plan
            signal, hook_msg = trigger("before_plan", ctx)
            if signal == "abort":
                final_content = hook_msg or "Aborted."
                break

            # hint and continue
            if ctx.pending_hint:
                messages.append({"role": "user", "content": f"[Hint] {ctx.pending_hint}"})
                ctx.pending_hint = None

            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                # Execute tools
                for tool_call in response.tool_calls:
                    if tools_actions and (tool_call.name not in tools_actions) and (
                        tool_call.name in [ReadFileTool.name, ]
                    ):
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"{tool_call.name} not in allow({tools_actions}), /abort"
                        ))
                    ctx.action = tool_call.name
                    ctx.params = tool_call.arguments

                    # Hooks: before_act
                    signal, hook_msg = trigger("before_act", ctx)
                    if signal == "abort":
                        final_content = hook_msg or "Aborted."
                        break
                    if signal == "hint":
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name,
                            f"Skipped by hook: {hook_msg}"
                        )
                        continue

                    args_str = json.dumps(tool_call.arguments)
                    result = await self._execute_tool_with_logging(
                        tool_name=tool_call.name,
                        params=tool_call.arguments,
                        session_key=msg.session_key,
                        channel=msg.channel,
                        chat_id=msg.chat_id
                    )
                    ico = str("√ " if not result.startswith("Error") else "× ")
                    logger.debug(f"Executing tool({ico}): {tool_call.name} with arguments: {args_str}")
                    summary_tools.append(
                        ico +  str(tool_call.name) +  str(tool_call.arguments)
                    )
                    ctx.observation = result
                    ctx.action_history.append({
                        "name": tool_call.name,
                        "params": tool_call.arguments
                    })
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                    trigger("after_act", ctx)
            else:
                # No tool calls, we're done
                final_content = response.content
                break

            ctx.loop_count += 1

        summary_tools = [
            item if len(item) < 70 else item[:70]
            for item in summary_tools
        ]
        # out iteration, summary
        if self.abort or ctx.force_summary or (final_content is None and ctx.loop_count == temp_max_iterations):
            logger.info("No final_content and out iteration, summary")
            # 放弃缓存, 全力压缩
            messages[0]['content'] == self.context.get_summary_context()
            messages.append({"role": "user", "content": self.context.get_user_summary_context()})
            response = await self.provider.chat(
                messages=messages,
                tools=None,
                model=self.model
            )
            final_content = response.content
            try:
                # parse contains two root-level tags
                root = ET.fromstring(f"<root>{final_content}</root>")
                logger.info(f"{root.find('analysis').text}")
                final_content = root.find('summary').text
            except Exception as e:
                logger.error(f'summary xml {e}', exc_info=True)
                start_summary = final_content.find('<summary>')
                end_summary = final_content.find('</summary>')
                if start_summary != -1 and end_summary:
                    final_content = final_content[start_summary:end_summary]

        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        collapsible_content = None
        if summary_tools:
            collapsible_content = '🔧 工具使用:\n' + '\n'.join(summary_tools)
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata={"collapsible": collapsible_content} if collapsible_content else {}
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    result = await self._execute_tool_with_logging(
                        tool_name=tool_call.name,
                        params=tool_call.arguments,
                        session_key=session_key,
                        channel=origin_channel,
                        chat_id=origin_chat_id
                    )
                    ico = str("√ " if not result.startswith("Error") else "× ")
                    logger.debug(f"Executing tool({ico}): {tool_call.name} with arguments: {args_str}")
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
        """
        Process a message directly (for CLI usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
