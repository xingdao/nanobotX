"""Skill execution tool for running skill scripts."""

import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.skills import SkillsLoader
from nanobot.utils.helpers import get_workspace_path

class ReadSkill(Tool):
    """Tool to load and execute skill scripts."""

    def __init__(self):
        self.workspace = get_workspace_path()
        self.skills_loader = SkillsLoader(self.workspace)

    @property
    def name(self) -> str:
        return "read_skill"

    @property
    def description(self) -> str:
        return "read skill documentation"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill (directory name)"
                }
            },
            "required": ["skill_name"]
        }

    async def execute(self, **kwargs: Any) -> str:
        return self.skills_loader.load_skill(kwargs.get("skill_name"))


class RunSkill(Tool):
    """Tool to load and execute skill scripts."""

    def __init__(self):
        self.workspace = get_workspace_path()
        self.skills_loader = SkillsLoader(self.workspace)
        self.exec_tool = ExecTool(timeout=120, restrict_to_workspace=True)

    @property
    def name(self) -> str:
        return "run_skill"

    @property
    def description(self) -> str:
        return "Execute skill scripts. "

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill"
                },
                "script": {
                    "type": "string",
                    "description": "Script to execute (e.g., 'scripts/tavily-search.py', 'scripts/xxx.sh', 'xxx.sh', 'yyy.sh'). Required"
                },
                "args": {
                    "type": "string",
                    "description": "Optional arguments to pass to the script"
                }
            },
            "required": ["script", "skill_name"]
        }

    async def execute(self, **kwargs: Any) -> str:
        skill_name = kwargs.get("skill_name")
        script = kwargs.get("script")
        args = kwargs.get("args")
        
        # Check if skill exists by trying to load it
        skill_content = self.skills_loader.load_skill(skill_name)
        if not skill_content:
            all_skills = [x["name"] for x in self.skills_loader.list_skills()]
            return f'Error: No skill {skill_name}, all skill is {all_skills}'
        
        # Get skill directory path
        skill_dir = self.skills_loader.workspace_skills / skill_name
        if not skill_dir.exists():
            # Check built-in skills if workspace skill doesn't exist
            if self.skills_loader.builtin_skills:
                skill_dir = self.skills_loader.builtin_skills / skill_name
                if not skill_dir.exists():
                    return f'Error: skill directory {skill_name} not found'
            else:
                return f'Error: skill directory {skill_name} not found'
        
        # Check if script file exists
        # TODO 防止目录穿越
        script_path = skill_dir / script
        if not script_path.exists():
            return f'Error: script file {script} not found in skill {skill_name} directory'
        full_command = ''
        # Check if script file is executable or a script
        if not (script_path.is_file() and os.access(script_path, os.X_OK)):
            # For non-executable files, check if they have a shebang or are Python scripts
            try:
                with open(script_path, 'r') as f:
                    first_line = f.readline()
                    if not (first_line.startswith('#!') or script_path.suffix == '.py'):
                        return f'Error: script file {script} is not executable and does not appear to be a script'
                # add python3
                full_command = 'python3 '
            except Exception:
                return f'Error: cannot read script file {script}'
        
        # Load environment variables from .env file
        env_vars = self.skills_loader.load_env(skill_name)
        full_command += f'{script_path} {args}' if args else str(script_path)
        
        # Set environment variables for the command
        skill_env = os.environ.copy()
        try:
            # Add skill's env vars to environment
            for key, value in env_vars.items():
                skill_env[key] = value

            # Execute the command
            result = await self.exec_tool.execute(
                command=full_command,
                working_dir=str(skill_dir),
                env=skill_env
            )

            # Add context about what was executed
            result = f"Success: {full_command}\nWorking directory: {skill_dir}\n\n{result}"

            return result

        except Exception as e:
            return f"Error executing skill script: {str(e)}"
