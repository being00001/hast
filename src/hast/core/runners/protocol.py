"""ProtocolRunner: auto export/wait/ingest bridge for external orchestrators."""

from __future__ import annotations

import json
from pathlib import Path

from hast.core.config import Config
from hast.core.errors import HastError
from hast.core.goals import Goal
from hast.core.protocol_adapters import (
    SUPPORTED_PROTOCOL_ADAPTERS,
    archive_result_packet,
    export_protocol_task_packet,
    ingest_protocol_result_packet,
    load_protocol_adapter_policy,
    wait_for_result_packet,
)
from hast.core.runner import GoalRunner, RunnerResult


class ProtocolRunner(GoalRunner):
    """Delegates execution to LangGraph/OpenHands via protocol packets."""

    def run(
        self,
        root: Path,
        config: Config,
        goal: Goal,
        prompt: str,
        tool_name: str | None = None,
    ) -> RunnerResult:
        del config  # protocol flow is policy-driven via .ai/policies/protocol_adapter_policy.yaml
        try:
            adapter = self._resolve_adapter(goal, tool_name)
            exported = export_protocol_task_packet(
                root,
                adapter=adapter,
                goal_id=goal.id,
                prompt_text=prompt,
                include_prompt=True,
                write_file=True,
            )
            packet_id = str(exported.packet.get("packet_id") or "")
            run_id = str(exported.packet.get("run_id") or "")
            match = wait_for_result_packet(
                root,
                adapter=adapter,
                goal_id=goal.id,
                packet_id=packet_id or None,
                run_id=run_id or None,
            )
            ingested = ingest_protocol_result_packet(root, match.packet)
            policy = load_protocol_adapter_policy(root)
            archived_path: Path | None = None
            if policy.archive_consumed_packets:
                archived_path = archive_result_packet(root, match.path)

            success = bool(match.packet.get("success"))
            output_payload = {
                "adapter": adapter,
                "goal_id": goal.id,
                "task_packet_path": exported.packet_path.as_posix() if exported.packet_path else None,
                "result_packet_path": match.path.as_posix(),
                "archived_result_packet_path": archived_path.as_posix() if archived_path else None,
                "ingested_run_id": ingested.run_id,
                "classification": match.packet.get("classification"),
                "action_taken": match.packet.get("action_taken"),
                "summary": match.packet.get("summary"),
            }
            return RunnerResult(
                success=success,
                output=json.dumps(output_payload, ensure_ascii=False, sort_keys=True),
                model_used=f"external:{adapter}",
            )
        except HastError as exc:
            return RunnerResult(success=False, output="", error_message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary
            return RunnerResult(success=False, output="", error_message=f"protocol runner failed: {exc}")

    def _resolve_adapter(self, goal: Goal, tool_name: str | None) -> str:
        candidate = tool_name or goal.tool
        if not isinstance(candidate, str) or not candidate.strip():
            raise HastError("protocol runner requires --tool langgraph|openhands (or goal.tool)")
        token = candidate.strip().lower()
        if token not in SUPPORTED_PROTOCOL_ADAPTERS:
            raise HastError(f"unsupported protocol adapter: {candidate}")
        return token
