"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, GlobTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool
from nanobot.config.schema import ExecToolConfig

class SubagentManager:
    """
    Manages background subagent execution.
    
    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
    ):
        
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.exec_config = exec_config or ExecToolConfig()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
    
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        wait: bool = False,
        read_only: bool = False,
    ) -> str:
        """
        Spawn a subagent to execute a task.

        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
            wait: If True, wait for completion and return result directly.
            read_only: If True, only allow read operations (no file writes, no shell).

        Returns:
            If wait=True: the subagent's result.
            If wait=False: status message indicating subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }

        if wait:
            logger.info(f"Running subagent [{task_id}] in sync mode: {display_label}")
            return await self._run_subagent_sync(task_id, task, display_label, read_only)

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, read_only)
        )
        self._running_tasks[task_id] = bg_task
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))

        logger.info(f"Spawned subagent [{task_id}]: {display_label}")
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    
    def _get_tools(self, read_only: bool) -> ToolRegistry:
        """Build tool registry for subagent."""
        tools = ToolRegistry()
        tools.register(ReadFileTool())
        tools.register(GlobTool())
        tools.register(WebFetchTool())
        if not read_only:
            tools.register(WriteFileTool())
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.exec_config.restrict_to_workspace,
            ))
        return tools

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        read_only: bool = False,
    ) -> None:
        """Execute the subagent task in background and announce the result."""
        logger.info(f"Subagent [{task_id}] starting task: {label}")

        try:
            tools = self._get_tools(read_only)
            system_prompt = self._build_subagent_prompt(task, read_only)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            final_result = await self._run_agent_loop(task_id, tools, messages)

            logger.info(f"Subagent [{task_id}] completed successfully")
            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"Subagent [{task_id}] failed: {e}")
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    async def _run_subagent_sync(
        self,
        task_id: str,
        task: str,
        label: str,
        read_only: bool = False,
    ) -> str:
        """Execute the subagent task synchronously and return result."""
        logger.info(f"Subagent [{task_id}] starting sync task: {label}")

        try:
            tools = self._get_tools(read_only)
            system_prompt = self._build_subagent_prompt(task, read_only)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            final_result = await self._run_agent_loop(task_id, tools, messages)
            logger.info(f"Subagent [{task_id}] sync completed successfully")
            return final_result

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"Subagent [{task_id}] sync failed: {e}")
            return error_msg

    async def _run_agent_loop(
        self,
        task_id: str,
        tools: ToolRegistry,
        messages: list[dict[str, Any]],
    ) -> str:
        """Run the agent loop and return final result."""
        max_iterations = 15
        iteration = 0
        final_result: str | None = None

        while iteration < max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=tools.get_definitions(),
                model=self.model,
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": tool_call_dicts,
                })

                for tool_call in response.tool_calls:
                    logger.debug(f"Subagent [{task_id}] executing: {tool_call.name}")
                    result = await tools.execute(tool_call.name, tool_call.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result,
                    })
            else:
                final_result = response.content
                break

        if final_result is None:
            final_result = "Task completed but no final response was generated."

        return final_result
    
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"
        
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )
        
        await self.bus.publish_inbound(msg)
        logger.debug(f"Subagent [{task_id}] announced result to {origin['channel']}:{origin['chat_id']}")
    
    def _build_subagent_prompt(self, task: str, read_only: bool = False) -> str:
        """Build a focused system prompt for the subagent."""
        base_prompt = f"""# Subagent

Given the user's message, you should use the tools available to complete the task.
Do what has been asked; nothing more, nothing less.
When you complete the task simply respond with a detailed writeup.

## Your Task
{task}

## Workspace
Your workspace is at: {self.workspace}

When you complete the task simply respond with a detailed writeup."""

        if read_only:
            base_prompt += """

## Read-Only Mode
You are in read-only exploration mode. You can ONLY:
- Read files
- Search for files
- Fetch web content

You CANNOT:
- Write or modify any files
- Execute shell commands

Focus on gathering information and providing insights."""
        else:
            base_prompt += """

## Notice
- Complete the task thoroughly
- NEVER Spawn other subagents
- NEVER create files unless they're absolutely necessary for achieving your goal. ALWAYS prefer editing an existing file to creating a new one.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the Task."""

        return base_prompt
    
    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
