"""Tests for docs freshness policy loading."""

from __future__ import annotations

from pathlib import Path
import textwrap

from hast.core.docs_policy import load_docs_policy, match_high_risk_paths


def test_load_docs_policy_defaults(tmp_path: Path) -> None:
    policy = load_docs_policy(tmp_path)
    assert policy.version == "v1"
    assert policy.freshness.warn_stale is True
    assert policy.freshness.block_on_high_risk is True
    assert "pyproject.toml" in policy.freshness.high_risk_path_patterns


def test_load_docs_policy_custom(tmp_path: Path) -> None:
    policies = tmp_path / ".ai" / "policies"
    policies.mkdir(parents=True, exist_ok=True)
    (policies / "docs_policy.yaml").write_text(
        textwrap.dedent(
            """\
            version: v2
            freshness:
              warn_stale: false
              block_on_high_risk: false
              high_risk_path_patterns:
                - "src/**/*.rs"
                - "infra/**"
            """
        ),
        encoding="utf-8",
    )

    policy = load_docs_policy(tmp_path)
    assert policy.version == "v2"
    assert policy.freshness.warn_stale is False
    assert policy.freshness.block_on_high_risk is False
    assert policy.freshness.high_risk_path_patterns == ["src/**/*.rs", "infra/**"]


def test_match_high_risk_paths() -> None:
    matched = match_high_risk_paths(
        [Path("src/core/auth.py"), Path("src/main.py"), Path("pyproject.toml")],
        ["src/**/auth*.py", "pyproject.toml"],
    )
    assert matched == [Path("pyproject.toml"), Path("src/core/auth.py")]
