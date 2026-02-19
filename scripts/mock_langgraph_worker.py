#!/usr/bin/env python3
"""Minimal mock LangGraph worker for devf protocol roundtrip tests.

By default the worker scans both:
- <project-root>/.ai/protocols/outbox
- <project-root>/.worktrees/*/.ai/protocols/outbox
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock LangGraph protocol worker")
    parser.add_argument("--project-root", required=True, help="Project root containing .ai/")
    parser.add_argument("--once", action="store_true", help="Exit after processing one packet")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Overall timeout")
    parser.add_argument(
        "--goal-id",
        help="Optional goal id filter. When set, only packets for this goal are processed.",
    )
    parser.add_argument(
        "--scan-worktrees",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also scan <project-root>/.worktrees/* outboxes (default: true).",
    )
    parser.add_argument(
        "--write-value",
        type=int,
        default=2,
        help="Value to write to target python file as VALUE=<n>",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()

    deadline = time.time() + max(1, args.timeout_seconds)
    seen: set[str] = set()

    while time.time() < deadline:
        for workspace_root, packet_path in _iter_packet_locations(root, scan_worktrees=args.scan_worktrees):
            if packet_path.as_posix() in seen:
                continue
            packet = _load_packet(packet_path)
            if packet is None:
                continue

            goal_id = str(packet.get("goal", {}).get("goal_id") or "")
            if args.goal_id and goal_id != args.goal_id:
                continue
            seen.add(packet_path.as_posix())

            target_path = _resolve_target_file(workspace_root, packet)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                f"VALUE = {args.write_value}\n",
                encoding="utf-8",
            )

            result_packet = {
                "schema_version": "protocol_result.v1",
                "adapter": str(packet.get("adapter") or "langgraph"),
                "packet_id": str(packet.get("packet_id") or ""),
                "goal_id": goal_id,
                "run_id": str(packet.get("run_id") or ""),
                "phase": str(packet.get("goal", {}).get("phase") or "implement"),
                "attempt": 1,
                "success": True,
                "classification": "complete",
                "action_taken": "advance",
                "summary": "mock langgraph worker applied deterministic edit",
            }
            inbox = workspace_root / ".ai" / "protocols" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            result_name = f"result_{packet.get('packet_id') or int(time.time())}.json"
            (inbox / result_name).write_text(
                json.dumps(result_packet, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            print(
                f"[mock-langgraph] processed {packet_path} -> "
                f"{(inbox / result_name).as_posix()}"
            )
            if args.once:
                return 0

        time.sleep(0.2)

    print("[mock-langgraph] timeout waiting for protocol task packet")
    return 1


def _load_packet(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != "protocol_task.v1":
        return None
    return data


def _resolve_target_file(root: Path, packet: dict) -> Path:
    goal = packet.get("goal")
    if isinstance(goal, dict):
        allowed = goal.get("allowed_changes")
        if isinstance(allowed, list):
            for item in allowed:
                if isinstance(item, str) and item.strip():
                    return root / item.strip()
    return root / "src" / "app.py"


def _iter_packet_locations(root: Path, *, scan_worktrees: bool) -> list[tuple[Path, Path]]:
    locations: list[tuple[Path, Path]] = []
    for workspace_root in _iter_workspace_roots(root, scan_worktrees=scan_worktrees):
        outbox = workspace_root / ".ai" / "protocols" / "outbox"
        if not outbox.exists():
            continue
        for packet_path in sorted(outbox.glob("*.json")):
            locations.append((workspace_root, packet_path))
    return locations


def _iter_workspace_roots(root: Path, *, scan_worktrees: bool) -> list[Path]:
    roots: list[Path] = [root]
    if not scan_worktrees:
        return roots

    worktrees_root = root / ".worktrees"
    if not worktrees_root.exists() or not worktrees_root.is_dir():
        return roots

    for child in sorted(worktrees_root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / ".ai").exists():
            continue
        roots.append(child)
    return roots


if __name__ == "__main__":
    raise SystemExit(main())
