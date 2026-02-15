"""WikiLink vault sync for `.knowledge/`."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import json
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from devf.core.goals import Goal, iter_goals, load_goals

_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
_NOTE_ID_SANITIZE = re.compile(r"[^A-Za-z0-9_]+")


@dataclass(frozen=True)
class DecisionEntry:
    decision_id: str
    goal_id: str | None
    status: str
    selected_alternative: str
    owner: str
    question: str
    file_path: Path


@dataclass(frozen=True)
class RunEntry:
    run_id: str
    evidence_path: Path
    goal_ids: list[str]
    classifications: dict[str, int]
    row_count: int


@dataclass(frozen=True)
class ContractEntry:
    contract_id: str
    file_path: Path
    exists: bool


@dataclass(frozen=True)
class VaultSyncResult:
    output_dir: Path
    generated_paths: list[Path]
    broken_links: list[str] = field(default_factory=list)
    orphan_notes: list[Path] = field(default_factory=list)


def sync_vault(root: Path, *, check_links: bool = True) -> VaultSyncResult:
    vault_dir = root / ".knowledge"
    goal_dir = vault_dir / "Goal"
    decision_dir = vault_dir / "Decision"
    run_dir = vault_dir / "Run"
    contract_dir = vault_dir / "Contract"
    for path in (vault_dir, goal_dir, decision_dir, run_dir, contract_dir):
        path.mkdir(parents=True, exist_ok=True)

    goals = _load_goal_items(root)
    decisions = _load_decision_entries(root)
    runs = _load_run_entries(root)
    contracts = _collect_contract_entries(root, goals)
    generated_at = datetime.now().astimezone().isoformat()

    goal_note_by_id = {goal.id: _note_id("G", goal.id) for goal in goals}
    decision_note_by_id = {decision.decision_id: _note_id("D", decision.decision_id) for decision in decisions}
    decision_note_by_file = {
        decision.file_path.as_posix(): decision_note_by_id[decision.decision_id]
        for decision in decisions
    }
    contract_note_by_file = {contract.file_path.as_posix(): contract.contract_id for contract in contracts}
    run_note_by_id = {run.run_id: _note_id("R", run.run_id) for run in runs}
    goal_to_runs = _build_goal_to_runs_map(runs)
    contract_to_goals = _build_contract_to_goals_map(goals)
    decisions_by_goal = _build_decisions_by_goal_map(decisions)

    generated_abs_paths: list[Path] = []

    generated_abs_paths.append(
        _write_markdown(vault_dir / "index.md", _render_root_index(generated_at))
    )
    generated_abs_paths.append(
        _write_markdown(
            goal_dir / "index.md",
            _render_goal_index(goals, goal_note_by_id, generated_at),
        )
    )
    generated_abs_paths.append(
        _write_markdown(
            decision_dir / "index.md",
            _render_decision_index(decisions, decision_note_by_id, generated_at),
        )
    )
    generated_abs_paths.append(
        _write_markdown(
            run_dir / "index.md",
            _render_run_index(runs, run_note_by_id, generated_at),
        )
    )
    generated_abs_paths.append(
        _write_markdown(
            contract_dir / "index.md",
            _render_contract_index(contracts, generated_at),
        )
    )

    for goal in goals:
        goal_note_id = goal_note_by_id[goal.id]
        decision_note_id = _resolve_goal_decision_note_id(
            goal,
            decisions_by_goal,
            decision_note_by_id,
            decision_note_by_file,
        )
        contract_note_id = _resolve_goal_contract_note_id(goal, contract_note_by_file)
        run_note_ids = sorted(run_note_by_id[run_id] for run_id in goal_to_runs.get(goal.id, set()))
        depends_on_note_ids = [
            goal_note_by_id[dep] for dep in goal.depends_on if dep in goal_note_by_id
        ]
        generated_abs_paths.append(
            _write_markdown(
                goal_dir / f"{goal_note_id}.md",
                _render_goal_note(
                    goal=goal,
                    goal_note_id=goal_note_id,
                    decision_note_id=decision_note_id,
                    contract_note_id=contract_note_id,
                    run_note_ids=run_note_ids,
                    depends_on_note_ids=depends_on_note_ids,
                    generated_at=generated_at,
                ),
            )
        )

    for decision in decisions:
        decision_note_id = decision_note_by_id[decision.decision_id]
        goal_note_id = (
            goal_note_by_id.get(decision.goal_id or "")
            if decision.goal_id
            else None
        )
        generated_abs_paths.append(
            _write_markdown(
                decision_dir / f"{decision_note_id}.md",
                _render_decision_note(
                    decision=decision,
                    decision_note_id=decision_note_id,
                    goal_note_id=goal_note_id,
                    generated_at=generated_at,
                ),
            )
        )

    for run in runs:
        run_note_id = run_note_by_id[run.run_id]
        goal_note_ids = [goal_note_by_id[goal_id] for goal_id in run.goal_ids if goal_id in goal_note_by_id]
        generated_abs_paths.append(
            _write_markdown(
                run_dir / f"{run_note_id}.md",
                _render_run_note(
                    run=run,
                    run_note_id=run_note_id,
                    goal_note_ids=goal_note_ids,
                    generated_at=generated_at,
                ),
            )
        )

    for contract in contracts:
        goal_note_ids = [
            goal_note_by_id[goal.id]
            for goal in contract_to_goals.get(contract.file_path.as_posix(), [])
            if goal.id in goal_note_by_id
        ]
        generated_abs_paths.append(
            _write_markdown(
                contract_dir / f"{contract.contract_id}.md",
                _render_contract_note(contract, goal_note_ids, generated_at),
            )
        )

    broken_links: list[str] = []
    orphan_notes: list[Path] = []
    if check_links:
        broken_links, orphan_notes = _inspect_vault_links(vault_dir)

    generated_paths = sorted(path.relative_to(root) for path in generated_abs_paths)
    return VaultSyncResult(
        output_dir=vault_dir.relative_to(root),
        generated_paths=generated_paths,
        broken_links=broken_links,
        orphan_notes=orphan_notes,
    )


def _load_goal_items(root: Path) -> list[Goal]:
    goals_path = root / ".ai" / "goals.yaml"
    if not goals_path.exists():
        return []
    goals = load_goals(goals_path)
    return [node.goal for node in iter_goals(goals)]


def _load_decision_entries(root: Path) -> list[DecisionEntry]:
    decisions_dir = root / ".ai" / "decisions"
    if not decisions_dir.exists():
        return []

    entries: list[DecisionEntry] = []
    for file_path in sorted(decisions_dir.glob("*.yaml")):
        data = _safe_read_yaml_mapping(file_path)
        if data is None:
            continue
        payload = data.get("decision", data)
        if not isinstance(payload, dict):
            continue
        decision_id = str(payload.get("decision_id") or file_path.stem).strip()
        if not decision_id:
            decision_id = file_path.stem
        goal_id_raw = str(payload.get("goal_id") or "").strip()
        entries.append(
            DecisionEntry(
                decision_id=decision_id,
                goal_id=goal_id_raw or None,
                status=str(payload.get("status") or "-"),
                selected_alternative=str(payload.get("selected_alternative") or "-"),
                owner=str(payload.get("owner") or "-"),
                question=str(payload.get("question") or "-"),
                file_path=file_path.relative_to(root),
            )
        )
    return entries


def _load_run_entries(root: Path) -> list[RunEntry]:
    runs_dir = root / ".ai" / "runs"
    if not runs_dir.exists():
        return []

    entries: list[RunEntry] = []
    for evidence_path in sorted(runs_dir.glob("*/evidence.jsonl")):
        run_id = evidence_path.parent.name
        goal_ids: set[str] = set()
        classifications: Counter[str] = Counter()
        row_count = 0
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            row_count += 1
            goal_id = row.get("goal_id")
            if isinstance(goal_id, str) and goal_id.strip():
                goal_ids.add(goal_id.strip())
            classification = row.get("classification")
            if isinstance(classification, str) and classification.strip():
                classifications[classification.strip()] += 1
        entries.append(
            RunEntry(
                run_id=run_id,
                evidence_path=evidence_path.relative_to(root),
                goal_ids=sorted(goal_ids),
                classifications=dict(sorted(classifications.items())),
                row_count=row_count,
            )
        )
    return entries


def _collect_contract_entries(root: Path, goals: list[Goal]) -> list[ContractEntry]:
    contract_paths: set[Path] = set()
    for goal in goals:
        if goal.contract_file:
            contract_paths.add(Path(goal.contract_file))

    contracts_dir = root / ".ai" / "contracts"
    if contracts_dir.exists():
        for pattern in ("**/*.yaml", "**/*.yml"):
            for file_path in sorted(contracts_dir.glob(pattern)):
                contract_paths.add(file_path.relative_to(root))

    used_ids: set[str] = set()
    entries: list[ContractEntry] = []
    for rel_path in sorted(contract_paths):
        logical_name = _logical_contract_name(rel_path)
        base_id = _note_id("C", logical_name)
        contract_id = base_id
        suffix = 2
        while contract_id in used_ids:
            contract_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(contract_id)
        entries.append(
            ContractEntry(
                contract_id=contract_id,
                file_path=Path(rel_path.as_posix()),
                exists=(root / rel_path).exists(),
            )
        )
    return entries


def _build_goal_to_runs_map(runs: list[RunEntry]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for run in runs:
        for goal_id in run.goal_ids:
            mapping.setdefault(goal_id, set()).add(run.run_id)
    return mapping


def _build_contract_to_goals_map(goals: list[Goal]) -> dict[str, list[Goal]]:
    mapping: dict[str, list[Goal]] = {}
    for goal in goals:
        if not goal.contract_file:
            continue
        key = Path(goal.contract_file).as_posix()
        mapping.setdefault(key, []).append(goal)
    for key in mapping:
        mapping[key] = sorted(mapping[key], key=lambda goal: goal.id)
    return mapping


def _build_decisions_by_goal_map(decisions: list[DecisionEntry]) -> dict[str, list[DecisionEntry]]:
    mapping: dict[str, list[DecisionEntry]] = {}
    for decision in decisions:
        if not decision.goal_id:
            continue
        mapping.setdefault(decision.goal_id, []).append(decision)
    for key in mapping:
        mapping[key] = sorted(mapping[key], key=lambda entry: entry.decision_id)
    return mapping


def _resolve_goal_decision_note_id(
    goal: Goal,
    decisions_by_goal: dict[str, list[DecisionEntry]],
    decision_note_by_id: dict[str, str],
    decision_note_by_file: dict[str, str],
) -> str | None:
    if goal.decision_file:
        direct = decision_note_by_file.get(Path(goal.decision_file).as_posix())
        if direct:
            return direct
    by_goal = decisions_by_goal.get(goal.id, [])
    if by_goal:
        return decision_note_by_id.get(by_goal[0].decision_id)
    return None


def _resolve_goal_contract_note_id(goal: Goal, contract_note_by_file: dict[str, str]) -> str | None:
    if not goal.contract_file:
        return None
    return contract_note_by_file.get(Path(goal.contract_file).as_posix())


def _render_root_index(generated_at: str) -> str:
    return (
        "# Knowledge Vault\n\n"
        f"- generated_at: `{generated_at}`\n\n"
        "## Navigation\n\n"
        f"- {_wikilink(Path('Goal/index.md'))}\n"
        f"- {_wikilink(Path('Decision/index.md'))}\n"
        f"- {_wikilink(Path('Run/index.md'))}\n"
        f"- {_wikilink(Path('Contract/index.md'))}\n"
    )


def _render_goal_index(
    goals: list[Goal],
    goal_note_by_id: dict[str, str],
    generated_at: str,
) -> str:
    lines = ["# Goal Notes", "", f"- generated_at: `{generated_at}`", ""]
    if goals:
        for goal in sorted(goals, key=lambda item: item.id):
            note_id = goal_note_by_id[goal.id]
            lines.append(f"- {_wikilink(Path(f'Goal/{note_id}.md'))} - {goal.title}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _render_decision_index(
    decisions: list[DecisionEntry],
    decision_note_by_id: dict[str, str],
    generated_at: str,
) -> str:
    lines = ["# Decision Notes", "", f"- generated_at: `{generated_at}`", ""]
    if decisions:
        for decision in sorted(decisions, key=lambda item: item.decision_id):
            note_id = decision_note_by_id[decision.decision_id]
            lines.append(f"- {_wikilink(Path(f'Decision/{note_id}.md'))} - {decision.status}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _render_run_index(
    runs: list[RunEntry],
    run_note_by_id: dict[str, str],
    generated_at: str,
) -> str:
    lines = ["# Run Notes", "", f"- generated_at: `{generated_at}`", ""]
    if runs:
        for run in sorted(runs, key=lambda item: item.run_id):
            note_id = run_note_by_id[run.run_id]
            lines.append(
                f"- {_wikilink(Path(f'Run/{note_id}.md'))} - rows={run.row_count} goals={len(run.goal_ids)}"
            )
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _render_contract_index(contracts: list[ContractEntry], generated_at: str) -> str:
    lines = ["# Contract Notes", "", f"- generated_at: `{generated_at}`", ""]
    if contracts:
        for contract in sorted(contracts, key=lambda item: item.contract_id):
            lines.append(
                f"- {_wikilink(Path(f'Contract/{contract.contract_id}.md'))} - {contract.file_path.as_posix()}"
            )
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _render_goal_note(
    *,
    goal: Goal,
    goal_note_id: str,
    decision_note_id: str | None,
    contract_note_id: str | None,
    run_note_ids: list[str],
    depends_on_note_ids: list[str],
    generated_at: str,
) -> str:
    lines = [
        f"# Goal {goal.id}",
        "",
        f"- note_id: `{goal_note_id}`",
        f"- title: `{goal.title}`",
        f"- status: `{goal.status}`",
        f"- state: `{goal.state or '-'}`",
        f"- phase: `{goal.phase or '-'}`",
        f"- owner_agent: `{goal.owner_agent or '-'}`",
        f"- generated_at: `{generated_at}`",
        "",
        "## Links",
        "",
    ]
    lines.append(
        "- Decision: "
        + (_wikilink(Path(f"Decision/{decision_note_id}.md")) if decision_note_id else "-")
    )
    lines.append(
        "- Contract: "
        + (_wikilink(Path(f"Contract/{contract_note_id}.md")) if contract_note_id else "-")
    )

    lines.append("- Depends on:")
    if depends_on_note_ids:
        for note_id in depends_on_note_ids:
            lines.append(f"  - {_wikilink(Path(f'Goal/{note_id}.md'))}")
    else:
        lines.append("  - (none)")

    lines.append("- Runs:")
    if run_note_ids:
        for run_note_id in run_note_ids:
            lines.append(f"  - {_wikilink(Path(f'Run/{run_note_id}.md'))}")
    else:
        lines.append("  - (none)")

    if goal.notes:
        lines.extend(["", "## Notes", "", goal.notes])
    return "\n".join(lines) + "\n"


def _render_decision_note(
    *,
    decision: DecisionEntry,
    decision_note_id: str,
    goal_note_id: str | None,
    generated_at: str,
) -> str:
    lines = [
        f"# Decision {decision.decision_id}",
        "",
        f"- note_id: `{decision_note_id}`",
        f"- source: `{decision.file_path.as_posix()}`",
        f"- status: `{decision.status}`",
        f"- selected_alternative: `{decision.selected_alternative}`",
        f"- owner: `{decision.owner}`",
        f"- generated_at: `{generated_at}`",
        "",
        "## Links",
        "",
    ]
    lines.append(
        "- Goal: "
        + (_wikilink(Path(f"Goal/{goal_note_id}.md")) if goal_note_id else "-")
    )
    lines.extend(["", "## Question", "", decision.question])
    return "\n".join(lines) + "\n"


def _render_run_note(
    *,
    run: RunEntry,
    run_note_id: str,
    goal_note_ids: list[str],
    generated_at: str,
) -> str:
    lines = [
        f"# Run {run.run_id}",
        "",
        f"- note_id: `{run_note_id}`",
        f"- source: `{run.evidence_path.as_posix()}`",
        f"- rows: `{run.row_count}`",
        f"- generated_at: `{generated_at}`",
        "",
        "## Goals",
        "",
    ]
    if goal_note_ids:
        for note_id in goal_note_ids:
            lines.append(f"- {_wikilink(Path(f'Goal/{note_id}.md'))}")
    else:
        lines.append("- (none)")

    lines.extend(["", "## Classification Counts", ""])
    if run.classifications:
        for key, value in sorted(run.classifications.items()):
            lines.append(f"- {key}: `{value}`")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _render_contract_note(contract: ContractEntry, goal_note_ids: list[str], generated_at: str) -> str:
    lines = [
        f"# Contract {contract.contract_id}",
        "",
        f"- source: `{contract.file_path.as_posix()}`",
        f"- exists: `{str(contract.exists).lower()}`",
        f"- generated_at: `{generated_at}`",
        "",
        "## Linked Goals",
        "",
    ]
    if goal_note_ids:
        for note_id in goal_note_ids:
            lines.append(f"- {_wikilink(Path(f'Goal/{note_id}.md'))}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def _inspect_vault_links(vault_dir: Path) -> tuple[list[str], list[Path]]:
    notes = sorted(vault_dir.rglob("*.md"))
    note_rel_set = {note.relative_to(vault_dir) for note in notes}
    inbound: dict[Path, int] = {}
    broken: list[str] = []

    for source in notes:
        source_rel = source.relative_to(vault_dir)
        content = source.read_text(encoding="utf-8")
        for token in _extract_wikilinks(content):
            target_rel = _resolve_wikilink_target(source_rel, token)
            if target_rel is None:
                continue
            if target_rel in note_rel_set:
                inbound[target_rel] = inbound.get(target_rel, 0) + 1
            else:
                broken.append(f"{source_rel.as_posix()} -> {token}")

    orphan_candidates = sorted(rel for rel in note_rel_set if rel.name != "index.md")
    orphans = [rel for rel in orphan_candidates if inbound.get(rel, 0) == 0]
    return sorted(broken), sorted(orphans)


def _extract_wikilinks(text: str) -> list[str]:
    return [match.group(1).strip() for match in _WIKILINK_PATTERN.finditer(text)]


def _resolve_wikilink_target(source_rel: Path, token: str) -> Path | None:
    clean = token.split("|", 1)[0].split("#", 1)[0].strip()
    if not clean:
        return None

    if clean.startswith("/"):
        raw_target = PurePosixPath(clean.lstrip("/"))
    else:
        raw_target = PurePosixPath(clean)
        if len(raw_target.parts) == 1:
            raw_target = PurePosixPath(source_rel.parent.as_posix()) / raw_target
    if raw_target.suffix.lower() != ".md":
        raw_target = raw_target.with_suffix(".md")

    normalized = posixpath.normpath(raw_target.as_posix())
    if normalized.startswith("../"):
        return None
    return Path(normalized)


def _note_id(prefix: str, raw_id: str) -> str:
    normalized = _NOTE_ID_SANITIZE.sub("_", raw_id.strip()).strip("_")
    if not normalized:
        normalized = "item"
    if normalized.startswith(f"{prefix}_"):
        return normalized
    return f"{prefix}_{normalized}"


def _logical_contract_name(rel_path: Path) -> str:
    rel = rel_path.as_posix()
    if rel.startswith(".ai/contracts/"):
        rel = rel[len(".ai/contracts/") :]
    stem = rel
    for suffix in (".yaml", ".yml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.replace("/", "_").replace(".", "_")


def _wikilink(path: Path) -> str:
    return f"[[{path.with_suffix('').as_posix()}]]"


def _write_markdown(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _safe_read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    return data
