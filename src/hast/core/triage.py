"""Failure triage taxonomy and classifiers."""

from __future__ import annotations

TRIAGE_POLICY_VERSION = "v1"

TRIAGE_CLASSES = {
    "spec-ambiguous",
    "test-defect",
    "impl-defect",
    "env-flaky",
    "dep-build",
    "security",
}


def classify_failure(
    classification: str | None,
    reason: str | None = None,
    test_output: str | None = None,
) -> str:
    """Normalize internal failure labels into the triage taxonomy."""
    raw = (classification or "").lower()
    reason_text = (reason or "").lower()
    output_text = (test_output or "").lower()
    merged = " ".join([raw, reason_text, output_text])

    if (
        "security" in merged
        or "gitleaks" in merged
        or "semgrep" in merged
        or "trivy" in merged
        or "grype" in merged
        or "dependency_scan" in merged
        or "secret" in merged
    ):
        return "security"
    if "dependency" in merged or "build" in merged or "pip" in merged or "npm" in merged:
        return "dep-build"
    if "timeout" in merged or "flaky" in merged or "connection reset" in merged:
        return "env-flaky"
    if "modulenotfounderror" in merged or "importerror" in merged:
        return "env-flaky"
    if "spec" in merged or "contract" in merged or "decision" in merged or "red-gate" in merged:
        return "spec-ambiguous"
    if "test" in merged and "assert" in merged:
        return "test-defect"
    if raw in {"phase-violation", "no-progress", "failed-impl", "failed-syntax", "failed-unknown"}:
        return "impl-defect"
    if raw in {"failed-env", "failed-flaky"}:
        return "env-flaky"
    if raw in {"contract-violation", "red-gate-fail", "contract-invalid"}:
        return "spec-ambiguous"
    if raw in {"decision-pending", "decision-mismatch"}:
        return "spec-ambiguous"
    if raw in {"failed", "failed-test"}:
        return "impl-defect"
    return "impl-defect"
