"""Tests for coverage measurement."""

from __future__ import annotations

from hast.core.result import CoverageReport, FileCoverage


def test_coverage_report_creation():
    fc = FileCoverage(
        file="src/app.py",
        covered_lines=80,
        total_lines=100,
    )
    assert fc.percent == 80.0

    report = CoverageReport(
        files=(fc,),
        overall_percent=80.0,
    )
    assert len(report.files) == 1
    assert report.overall_percent == 80.0


def test_file_coverage_zero_lines():
    fc = FileCoverage(file="empty.py", covered_lines=0, total_lines=0)
    assert fc.percent == 0.0


from pathlib import Path
import textwrap

from hast.utils.coverage import measure_coverage


def _write_py(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_measure_coverage_basic(tmp_path: Path) -> None:
    """Measure coverage of a simple project."""
    _write_py(tmp_path, "src/calc.py", """\
        def add(a, b):
            return a + b

        def unused(x):
            return x * 2
    """)
    _write_py(tmp_path, "tests/test_calc.py", """\
        import sys
        sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'src'))
        from calc import add

        def test_add():
            assert add(1, 2) == 3
    """)

    report = measure_coverage(
        root=tmp_path,
        target_files=["src/calc.py"],
        test_command="pytest tests/ -q",
    )
    assert len(report.files) == 1
    assert report.files[0].file == "src/calc.py"
    # add() is covered, unused() is not — so coverage < 100%
    assert 0 < report.overall_percent < 100


def test_measure_coverage_no_tests(tmp_path: Path) -> None:
    """Project with no test files returns 0% coverage."""
    _write_py(tmp_path, "src/app.py", """\
        def main():
            pass
    """)
    (tmp_path / "tests").mkdir()
    report = measure_coverage(
        root=tmp_path,
        target_files=["src/app.py"],
        test_command="pytest tests/ -q",
    )
    assert report.overall_percent == 0.0
