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
from nanobot.agent.tools.web import WebFetchTool
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
        exec_config: "ExecToolConfig | None" = None,
        tool_logging_config: "ToolLoggingConfig | None" = None,
        cron_service: "CronService | None" = None,
    ):

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
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
            exec_config=self.exec_config,
        )

        register_default_rules()
        
        self._running = False
        self.abort = False
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(ReadSkill())
        self.tools.register(RunSkill())
        self.tools.register(EditFileTool())
        self.tools.register(GlobTool())
        
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        
        self.tools.register(WebFetchTool())
        
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
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
        """Execute a tool with logging and notification."""
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

    def _setup_session_tools(self, channel: str, chat_id: str) -> None:
        """Update tool contexts for session."""
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(channel, chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(channel, chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(channel, chat_id)

    async def _process_command(self, msg: InboundMessage) -> OutboundMessage | None:
        """Handle command messages like /restart, /config."""
        cout_content = f"{msg.content} command not support"
        if msg.content == '/restart':
            logger.info(f"Handling /restart command for session {msg.session_key}")
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
            self.sessions.get_or_create(msg.session_key).clear()
            cout_content = f"{msg.session_key} restart ok"
        elif msg.content == '/config':
            config = dict(model=self.model)
            cout_content = f"config:\n{config}"
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=cout_content
        )

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process a single inbound message."""
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        temp_max_iterations = self.max_iterations
        if msg.content.strip().startswith('好好想想'):
            temp_max_iterations = 50

        session = self.sessions.get_or_create(msg.session_key)
        self._setup_session_tools(msg.channel, msg.chat_id)

        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
        )
        
        tools_actions = await self._handle_plan_step(msg, messages, session)
        if msg.content.endswith('plan'):
            return None
        
        final_content = None
        summary_tools = []
        ctx = AgentContext(input=msg.content)
        
        while ctx.loop_count < temp_max_iterations and not self.abort:
            signal, hook_msg = trigger("before_plan", ctx)
            if signal == "abort":
                final_content = hook_msg or "Aborted."
                break

            if ctx.pending_hint:
                messages.append({"role": "user", "content": f"[Hint] {ctx.pending_hint}"})
                ctx.pending_hint = None

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
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(messages, response.content, tool_call_dicts)
                
                for tool_call in response.tool_calls:
                    success = await self._execute_single_tool(
                        tool_call, messages, msg.session_key, msg.channel, msg.chat_id,
                        ctx, tools_actions, summary_tools
                    )
                    if not success:
                        final_content = "Aborted."
                        break
            else:
                final_content = response.content
                break

            ctx.loop_count += 1

        summary_content = await self._generate_summary_if_needed(
            messages, ctx, temp_max_iterations, final_content
        )
        if summary_content:
            final_content = summary_content

        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        collapsible_content = None
        if summary_tools:
            collapsible_content = '🔧 工具使用:\n' + '\n'.join(
                item if len(item) < 70 else item[:70] for item in summary_tools
            )
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata={"collapsible": collapsible_content} if collapsible_content else {}
        )

    async def _handle_plan_step(self, msg: InboundMessage, messages: list, session) -> str | None:
        """Handle plan step if message contains plan keyword."""
        if not any(x in msg.content.split('\n', 1)[0] for x in ('plan', '计划')):
            return None
        
        plan_prompt = self.context.build_plan_prompt()
        if not plan_prompt:
            return None
        
        plan_messages = self.context.build_messages(
            history=session.get_history(),
            current_message=f"{plan_prompt}\n\n## 用户任务\n\n{msg.content}",
            media=msg.media if msg.media else None,
        )
        plan_response = await self.provider.chat(
            messages=plan_messages,
            model='deepseek/deepseek-reasoner'
        )
        logger.info(f"Executing plan {plan_response}")
        
        try:
            root = ET.fromstring(f"<root>{plan_response.content}</root>")
            clarity_elem = root.find("clarity")
            if clarity_elem is not None and clarity_elem.text and clarity_elem.text.lower() == "false":
                unclear_elem = root.find("unclear_points")
                unclear_text = unclear_elem.text if unclear_elem is not None else "The plan is unclear."
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id, content=unclear_text
                ))
                return None
            
            task = root.findtext("task") or ""
            tools_actions = root.findtext("tools_and_actions") or ""
            warnings = root.findtext("warnings") or ""
            plan_addition = f"\n\n## Plan\n\n**Task:** {task}\n\n**Tools and Actions:** {tools_actions}\n\n**Warnings:** {warnings}"
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=f"plan_addition:{plan_addition}"
            ))
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] = msg.content + plan_addition
            return tools_actions
        except ET.ParseError as e:
            logger.warning(f"Failed to parse plan XML: {e}")
        except Exception as e:
            logger.warning(f"Error during plan step: {e}", exc_info=True)
        
        return None

    async def _execute_single_tool(self, tool_call, messages: list, session_key: str,
                                   channel: str, chat_id: str, ctx: AgentContext,
                                   tools_actions: str | None, summary_tools: list) -> bool:
        """Execute a single tool call and return True if should continue."""
        if tools_actions and (tool_call.name not in tools_actions) and (tool_call.name in [ReadFileTool.name]):
            await self.bus.publish_outbound(OutboundMessage(
                channel=channel, chat_id=chat_id,
                content=f"{tool_call.name} not in allow({tools_actions}), /abort"
            ))
        
        ctx.action = tool_call.name
        ctx.params = tool_call.arguments
        signal, hook_msg = trigger("before_act", ctx)
        
        if signal == "abort":
            return False
        if signal == "hint":
            messages.append({"role": "user", "content": f"[Hint] {hook_msg}"})
            ctx.pending_hint = None
            messages = self.context.add_tool_result(
                messages, tool_call.id, tool_call.name, f"Skipped by hook: {hook_msg}"
            )
            return True
        
        result = await self._execute_tool_with_logging(
            tool_call.name, tool_call.arguments, session_key, channel, chat_id
        )
        ico = "√ " if not result.startswith("Error") else "× "
        logger.debug(f"Executing tool({ico}): {tool_call.name} with arguments: {json.dumps(tool_call.arguments)}")
        summary_tools.append(ico + tool_call.name + str(tool_call.arguments))
        
        ctx.observation = result
        ctx.action_history.append({"name": tool_call.name, "params": tool_call.arguments})
        messages = self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
        trigger("after_act", ctx)
        return True

    async def _generate_summary_if_needed(self, messages: list, ctx: AgentContext,
                                           temp_max_iterations: int, final_content: str | None) -> str | None:
        """Generate summary if needed (abort, force_summary, or max iterations reached)."""
        if not (self.abort or ctx.force_summary or (final_content is None and ctx.loop_count == temp_max_iterations)):
            return None
        
        logger.info("No final_content and out iteration, summary")
        messages[0]['content'] = self.context.get_summary_context()
        messages.append({"role": "user", "content": self.context.get_user_summary_context()})
        response = await self.provider.chat(messages=messages, tools=None, model=self.model)
        final_content = response.content
        
        try:
            root = ET.fromstring(f"<root>{final_content}</root>")
            logger.info(f"{root.find('analysis').text}")
            final_content = root.find('summary').text
        except Exception as e:
            logger.error(f'summary xml {e}', exc_info=True)
            start = final_content.find('<summary>')
            end = final_content.find('</summary>')
            if start != -1 and end != -1:
                final_content = final_content[start:end]
        
        return final_content
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process a system message (e.g., subagent announce)."""
        logger.info(f"Processing system message from {msg.sender_id}")
        
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        self._setup_session_tools(origin_channel, origin_chat_id)
        
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content
        )
        
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
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(messages, response.content, tool_call_dicts)
                
                for tool_call in response.tool_calls:
                    result = await self._execute_tool_with_logging(
                        tool_call.name, tool_call.arguments, session_key, origin_channel, origin_chat_id
                    )
                    ico = "√ " if not result.startswith("Error") else "× "
                    logger.debug(f"Executing tool({ico}): {tool_call.name}")
                    messages = self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
        """Process a message directly (for CLI usage)."""
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""