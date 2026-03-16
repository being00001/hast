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
