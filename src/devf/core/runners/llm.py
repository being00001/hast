"""LLM-based goal runner using litellm."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from litellm import completion

from devf.core.config import Config, ModelConfig
from devf.core.goals import Goal
from devf.core.runner import GoalRunner, RunnerResult
from devf.core.phase import PHASE_AGENT_MAP


class LLMRunner(GoalRunner):
    """Executes AI sessions by calling an LLM via litellm."""

    def run(
        self,
        root: Path,
        config: Config,
        goal: Goal,
        prompt: str,
        tool_name: str | None = None,
    ) -> RunnerResult:
        model_config = self._resolve_model_config(config, goal, tool_name)
        if not model_config or not model_config.model:
            return RunnerResult(
                success=False,
                output="",
                error_message="No model configuration found for this task (roles.worker.model missing?).",
            )

        print(f"[LLM] invoking {model_config.model} (temp={model_config.temperature})...", file=sys.stderr)
        
        try:
            started = time.perf_counter()
            # Handle API Key from Env Var syntax ($VAR_NAME)
            api_key = model_config.api_key
            if api_key and api_key.startswith("$"):
                var_name = api_key[1:]
                api_key = os.environ.get(var_name)
            
            # --- Prompt Caching Logic ---
            messages = self._build_messages_with_cache(prompt, model_config.model)
            
            response = completion(
                model=model_config.model,
                messages=messages,
                temperature=model_config.temperature,
                max_tokens=model_config.max_tokens,
                api_key=api_key, 
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            
            content = response.choices[0].message.content
            usage = getattr(response, "usage", None)
            prompt_tokens = _get_usage_value(usage, "prompt_tokens")
            completion_tokens = _get_usage_value(usage, "completion_tokens")
            return RunnerResult(
                success=True,
                output=content,
                model_used=model_config.model,
                latency_ms=latency_ms,
                cost_tokens_prompt=prompt_tokens,
                cost_tokens_completion=completion_tokens,
            )

        except Exception as exc:
            return RunnerResult(
                success=False,
                output="",
                error_message=f"LLM execution failed: {str(exc)}",
            )

    def _build_messages_with_cache(self, prompt: str, model: str) -> list[dict]:
        """Split prompt and apply caching if supported."""
        
        # Check support: Anthropic and DeepSeek
        supports_caching = False
        if "anthropic" in model.lower() or "claude" in model.lower():
            supports_caching = True
        elif "deepseek" in model.lower():
            supports_caching = True
            
        if not supports_caching:
            return [{"role": "user", "content": prompt}]

        # Split: Context <---> Instructions
        # defined in src/devf/core/auto.py as "\n\n---\n\n"
        separator = "\n\n---\n\n"
        parts = prompt.split(separator, 1)
        
        if len(parts) != 2:
            # Can't split cleanly, fallback to no cache
            return [{"role": "user", "content": prompt}]
            
        context_part = parts[0]
        instruction_part = separator + parts[1] # Keep separator for readability
        
        # Construct cached message
        # LiteLLM / Anthropic format: 
        # content = [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]
        
        cached_content_block = {
            "type": "text", 
            "text": context_part,
            "cache_control": {"type": "ephemeral"}
        }
        
        instruction_content_block = {
            "type": "text",
            "text": instruction_part
        }
        
        return [
            {
                "role": "user",
                "content": [cached_content_block, instruction_content_block]
            }
        ]

    def _resolve_model_config(
        self, config: Config, goal: Goal, tool_name: str | None
    ) -> ModelConfig | None:
        # 1. CLI Override or explicit tool
        if tool_name:
            if tool_name == "architect":
                return config.roles.architect
            if tool_name == "worker":
                return config.roles.worker
            if tool_name == "tester":
                return config.roles.tester
            
        # 2. Goal Agent/Phase mapping to Role
        role = "worker" # Default
        
        if goal.agent == "architect" or goal.phase == "plan":
            role = "architect"
        elif goal.phase == "adversarial":
            role = "tester"
        
        if role == "architect":
            return config.roles.architect or config.roles.worker
        if role == "tester":
            return config.roles.tester or config.roles.worker
        
        return config.roles.worker


def _get_usage_value(usage: object, field_name: str) -> int | None:
    if usage is None:
        return None
    value = getattr(usage, field_name, None)
    if isinstance(value, int):
        return value
    if isinstance(usage, dict):
        dict_value = usage.get(field_name)
        if isinstance(dict_value, int):
            return dict_value
    return None
