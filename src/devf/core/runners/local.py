"""Local process-based goal runner."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from devf.core.config import Config
from devf.core.errors import DevfError
from devf.core.goals import Goal
from devf.core.phase import PHASE_AGENT_MAP
from devf.core.runner import GoalRunner, RunnerResult


class LocalRunner(GoalRunner):
    """Executes AI sessions by running a local shell command."""

    def run(
        self,
        root: Path,
        config: Config,
        goal: Goal,
        prompt: str,
        tool_name: str | None = None,
    ) -> RunnerResult:
        tool_command = self._resolve_tool_command(config, goal, tool_name)
        timeout = config.timeout_minutes * 60

        prompt_file_path: str | None = None
        command = tool_command
        
        # Prepare command and prompt file if needed
        if "{prompt_file}" in command:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, dir=str(root / ".ai")
            ) as handle:
                handle.write(prompt)
                prompt_file_path = handle.name
            command = command.replace("{prompt_file}", shlex.quote(prompt_file_path))
        
        if "{prompt}" in command:
            command = command.replace("{prompt}", shlex.quote(prompt))

        # Strip env vars that prevent nested AI tool invocation
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        try:
            proc = subprocess.run(
                command,
                cwd=str(root),
                shell=True,
                check=False,
                timeout=timeout,
                capture_output=True,
                text=True,
                env=env,
            )
            return RunnerResult(
                success=proc.returncode == 0,
                output=proc.stdout + (proc.stderr or ""),
            )
        except subprocess.TimeoutExpired:
            return RunnerResult(
                success=False,
                output="",
                error_message=f"AI tool timed out after {config.timeout_minutes} minutes",
            )
        except Exception as exc:
            return RunnerResult(
                success=False,
                output="",
                error_message=str(exc),
            )
        finally:
            if prompt_file_path:
                try:
                    Path(prompt_file_path).unlink()
                except OSError:
                    pass

    def _resolve_tool_command(self, config: Config, goal: Goal, tool_name: str | None) -> str:
        # Priority: goal.tool > tool_name (CLI) > goal.agent > phase default > config default
        name = goal.tool or tool_name or goal.agent
        if name is None and goal.phase:
            name = PHASE_AGENT_MAP.get(goal.phase)
        if name:
            if name not in config.ai_tools:
                raise DevfError(f"tool not found in config.ai_tools: {name}")
            return config.ai_tools[name]
        return config.ai_tool
