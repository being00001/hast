"""Test coverage measurement using coverage.py."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from hast.core.result import CoverageReport, FileCoverage


def measure_coverage(
    root: Path,
    target_files: list[str] | None = None,
    test_command: str | None = None,
) -> CoverageReport:
    """Run tests with coverage and return a report for target files.

    Args:
        root: Project root directory.
        target_files: Relative paths to measure coverage for. If None, all .py files.
        test_command: Test command (e.g. "pytest tests/ -q"). Defaults to "pytest tests/ -q".

    Returns:
        CoverageReport with per-file and overall coverage data.
    """
    test_cmd = test_command or "pytest tests/ -q"

    with tempfile.TemporaryDirectory() as tmpdir:
        data_file = Path(tmpdir) / ".coverage"
        json_file = Path(tmpdir) / "coverage.json"

        source_dir = str(root / "src")

        python = sys.executable

        cmd_parts = [
            python, "-m", "coverage", "run",
            f"--data-file={data_file}",
            f"--source={source_dir}",
            "-m",
        ] + shlex.split(test_cmd)

        try:
            subprocess.run(
                cmd_parts,
                cwd=str(root),
                capture_output=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return CoverageReport()

        if not data_file.exists():
            return CoverageReport()

        try:
            subprocess.run(
                [
                    python, "-m", "coverage", "json",
                    f"--data-file={data_file}",
                    "-o", str(json_file),
                ],
                cwd=str(root),
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return CoverageReport()

        if not json_file.exists():
            return CoverageReport()

        return _parse_coverage_json(json_file, root, target_files)


def _parse_coverage_json(
    json_path: Path,
    root: Path,
    target_files: list[str] | None,
) -> CoverageReport:
    """Parse coverage.py JSON output into CoverageReport."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    files_data = data.get("files", {})

    file_coverages: list[FileCoverage] = []
    total_covered = 0
    total_lines = 0

    for file_path_str, info in files_data.items():
        file_path = Path(file_path_str)
        if file_path.is_absolute():
            try:
                rel = str(file_path.relative_to(root))
            except ValueError:
                continue
        else:
            rel = str(file_path)

        if target_files and rel not in target_files:
            continue

        summary = info.get("summary", {})
        covered = summary.get("covered_lines", 0)
        num_statements = summary.get("num_statements", 0)

        file_coverages.append(FileCoverage(
            file=rel,
            covered_lines=covered,
            total_lines=num_statements,
        ))
        total_covered += covered
        total_lines += num_statements

    overall = round(total_covered / total_lines * 100, 1) if total_lines > 0 else 0.0

    return CoverageReport(
        files=tuple(file_coverages),
        overall_percent=overall,
    )
