"""Read-only design-question exploration over the current codebase."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re

from hast.core.analysis import SymbolMap, build_symbol_map
from hast.core.errors import HastError
from hast.utils.codetools import build_import_map, file_to_module, find_related_tests

_IGNORE_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    "node_modules",
    ".worktrees",
    "references",
}


@dataclass(frozen=True)
class ExploreMatch:
    path: str
    symbol: str
    kind: str
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExploreApproach:
    name: str
    summary: str
    tradeoffs: list[str]


@dataclass(frozen=True)
class ExploreReport:
    question: str
    terms: list[str]
    matches: list[ExploreMatch]
    callers_by_file: dict[str, list[str]]
    related_tests: list[str]
    impact: dict[str, int]
    approaches: list[ExploreApproach]


def explore_question(root: Path, question: str, *, max_matches: int = 20) -> ExploreReport:
    question_clean = question.strip()
    if not question_clean:
        raise HastError("question must be non-empty")
    if max_matches <= 0:
        raise HastError("max_matches must be positive")

    terms = _extract_terms(question_clean)
    symbol_map = build_symbol_map(root)
    matches = _collect_symbol_matches(symbol_map, terms, max_matches=max_matches)
    if not matches:
        matches = _collect_text_matches(root, terms, max_matches=max_matches)

    matched_files = sorted({m.path for m in matches})
    callers_by_file = _collect_callers(root, matched_files)
    related_tests = find_related_tests(root, matched_files)[:20] if matched_files else []

    impacted_files = set(matched_files)
    for callers in callers_by_file.values():
        impacted_files.update(callers)
    impacted_files.update(related_tests)

    impact = {
        "matched_files": len(matched_files),
        "caller_files": sum(len(v) for v in callers_by_file.values()),
        "related_tests": len(related_tests),
        "estimated_total_impacted_files": len(impacted_files),
    }

    approaches = _suggest_approaches(question_clean)
    return ExploreReport(
        question=question_clean,
        terms=terms,
        matches=matches,
        callers_by_file=callers_by_file,
        related_tests=related_tests,
        impact=impact,
        approaches=approaches,
    )


def report_to_dict(report: ExploreReport) -> dict[str, object]:
    return asdict(report)


def format_explore_report(report: ExploreReport) -> str:
    lines = [
        "# Explore Report",
        "",
        f"Question: {report.question}",
        f"Key terms: {', '.join(report.terms) if report.terms else '(none)'}",
        "",
        "Potential touch points:",
    ]
    if report.matches:
        for idx, match in enumerate(report.matches, start=1):
            reason = ", ".join(match.reasons[:3]) if match.reasons else "term overlap"
            lines.append(
                f"{idx}. {match.path} | {match.kind} {match.symbol} "
                f"(score={match.score}; {reason})"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Callers by file:"])
    if report.callers_by_file:
        for path in sorted(report.callers_by_file.keys()):
            callers = report.callers_by_file[path]
            if callers:
                lines.append(f"- {path}: {', '.join(callers[:8])}")
    else:
        lines.append("- none found")

    lines.extend(["", "Related tests:"])
    if report.related_tests:
        for item in report.related_tests:
            lines.append(f"- {item}")
    else:
        lines.append("- none found")

    lines.extend(
        [
            "",
            "Impact summary:",
            (
                f"- matched_files={report.impact['matched_files']}, "
                f"caller_files={report.impact['caller_files']}, "
                f"related_tests={report.impact['related_tests']}, "
                f"estimated_total_impacted_files={report.impact['estimated_total_impacted_files']}"
            ),
            "",
            "Candidate approaches:",
        ]
    )
    for idx, approach in enumerate(report.approaches, start=1):
        lines.append(f"{idx}. {approach.name}: {approach.summary}")
        for tradeoff in approach.tradeoffs:
            lines.append(f"   - {tradeoff}")

    lines.extend(
        [
            "",
            "Next step:",
            "Choose one approach, then run `hast decision new ...` before `hast auto`.",
        ]
    )
    return "\n".join(lines)


def _extract_terms(question: str) -> list[str]:
    # Keep signal-rich identifiers and dotted API fragments.
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_\.]*", question)
    terms: list[str] = []
    seen: set[str] = set()
    for token in raw:
        parts = [part for part in token.split(".") if part]
        for part in parts:
            if len(part) < 3:
                continue
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(part)
    return terms[:24]


def _collect_symbol_matches(
    symbol_map: SymbolMap,
    terms: list[str],
    *,
    max_matches: int,
) -> list[ExploreMatch]:
    results: list[ExploreMatch] = []
    seen: set[tuple[str, str, str]] = set()

    def add(path: str, symbol: str, kind: str, reasons: list[str]) -> None:
        key = (path, symbol, kind)
        if key in seen:
            return
        seen.add(key)
        score = len(reasons)
        if score <= 0:
            return
        results.append(
            ExploreMatch(
                path=path,
                symbol=symbol,
                kind=kind,
                score=score,
                reasons=sorted(reasons),
            )
        )

    for path, summary in symbol_map.files.items():
        for cls in summary.classes:
            reasons = _matched_terms(cls.name, terms)
            add(path, cls.name, "class", reasons)
            for method in cls.methods:
                symbol = f"{cls.name}.{method.name}"
                reasons = _matched_terms(symbol, terms)
                add(path, symbol, "method", reasons)

        for fn in summary.functions:
            reasons = _matched_terms(fn.name, terms)
            add(path, fn.name, "function", reasons)

    results.sort(key=lambda m: (-m.score, m.path, m.symbol))
    return results[:max_matches]


def _collect_text_matches(root: Path, terms: list[str], *, max_matches: int) -> list[ExploreMatch]:
    if not terms:
        return []
    results: list[ExploreMatch] = []
    for path in sorted(root.rglob("*.py")):
        rel = _safe_relpath(path, root)
        if rel is None:
            continue
        if any(part in _IGNORE_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lower = text.lower()
        reasons = sorted({term for term in terms if term.lower() in lower})
        if not reasons:
            continue
        results.append(
            ExploreMatch(
                path=rel,
                symbol="(text-hit)",
                kind="file",
                score=len(reasons),
                reasons=reasons,
            )
        )
    results.sort(key=lambda m: (-m.score, m.path))
    return results[:max_matches]


def _collect_callers(root: Path, matched_files: list[str]) -> dict[str, list[str]]:
    import_map, _ = build_import_map(root)
    result: dict[str, list[str]] = {}
    for rel in matched_files:
        module = file_to_module(rel)
        if not module:
            continue
        callers = sorted(import_map.get(module, []))
        if callers:
            result[rel] = callers[:20]
    return result


def _matched_terms(symbol: str, terms: list[str]) -> list[str]:
    name = symbol.lower()
    return sorted({term for term in terms if term.lower() in name})


def _suggest_approaches(question: str) -> list[ExploreApproach]:
    q = question.lower()
    if any(
        word in q
        for word in (
            "param",
            "parameter",
            "signature",
            "interface",
            "api",
            "파라미터",
            "인터페이스",
            "시그니처",
        )
    ):
        return [
            ExploreApproach(
                name="Backward-Compatible Signature Extension",
                summary="Add optional argument with safe default and thread it through top callers.",
                tradeoffs=[
                    "Lowest migration risk and easiest rollback.",
                    "Can accumulate optional-arg complexity if repeated.",
                ],
            ),
            ExploreApproach(
                name="Request Object / Context Dataclass",
                summary="Replace growing argument list with a typed context object.",
                tradeoffs=[
                    "Better long-term API stability and readability.",
                    "Requires broader touch points during first migration.",
                ],
            ),
            ExploreApproach(
                name="Adapter Layer",
                summary="Keep current interface and add thin adapter for new behavior path.",
                tradeoffs=[
                    "Minimizes immediate callsite churn.",
                    "May hide architectural debt if kept too long.",
                ],
            ),
        ]
    return [
        ExploreApproach(
            name="Minimal Local Change",
            summary="Patch the smallest surface to satisfy immediate behavior.",
            tradeoffs=["Fastest execution.", "May not scale to nearby use cases."],
        ),
        ExploreApproach(
            name="Explicit Adapter Boundary",
            summary="Introduce a clear wrapper between old and new contract.",
            tradeoffs=["Improves migration clarity.", "Adds short-term indirection."],
        ),
        ExploreApproach(
            name="Targeted Refactor",
            summary="Refactor contract + top dependents in one controlled batch.",
            tradeoffs=["Cleaner end state.", "Higher test and review burden."],
        ),
    ]


def _safe_relpath(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None
