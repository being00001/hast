"""CLI tests for docs commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from hast.cli import main
from hast.core.mermaid import MermaidRenderResult


def _seed_project(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "goals.yaml").write_text(
        """
goals:
  - id: G_DOCS
    title: doc goal
    status: active
""",
        encoding="utf-8",
    )


def test_docs_generate_command(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14"])
    assert result.exit_code == 0
    assert "Generated docs: 4 file(s)" in result.output
    assert "Mermaid diagrams:" in result.output
    assert (tmp_path / "docs" / "generated" / "codemap.md").exists()


def test_docs_generate_warns_when_stale(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    generated_dir = tmp_path / "docs" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stale = generated_dir / "codemap.md"
    stale.write_text("old\n", encoding="utf-8")

    stale_ts = 1_700_000_000
    fresh_ts = stale_ts + 1_000
    os.utime(stale, (stale_ts, stale_ts))
    os.utime(tmp_path / ".ai" / "goals.yaml", (fresh_ts, fresh_ts))

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14"])
    assert result.exit_code == 0
    assert "Stale docs detected before refresh:" in result.output
    assert "docs/generated/codemap.md" in result.output


def test_docs_generate_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["window_days"] == 14
    assert "docs/generated/codemap.md" in payload["generated_paths"]


def test_docs_generate_blocks_when_stale_and_high_risk(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    generated_dir = tmp_path / "docs" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stale = generated_dir / "codemap.md"
    stale.write_text("old\n", encoding="utf-8")
    high_risk = tmp_path / "src" / "core" / "auth_guard.py"
    high_risk.parent.mkdir(parents=True, exist_ok=True)
    high_risk.write_text("def check() -> bool:\n    return True\n", encoding="utf-8")

    stale_ts = 1_700_000_000
    fresh_ts = stale_ts + 1_000
    os.utime(stale, (stale_ts, stale_ts))
    os.utime(high_risk, (fresh_ts, fresh_ts))

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14"])
    assert result.exit_code == 1
    assert "Freshness policy block (high-risk stale sources):" in result.output
    assert "src/core/auth_guard.py" in result.output


def test_docs_generate_blocks_when_stale_and_high_risk_json(
    monkeypatch, tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    generated_dir = tmp_path / "docs" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stale = generated_dir / "codemap.md"
    stale.write_text("old\n", encoding="utf-8")
    high_risk = tmp_path / "src" / "core" / "auth_guard.py"
    high_risk.parent.mkdir(parents=True, exist_ok=True)
    high_risk.write_text("def check() -> bool:\n    return True\n", encoding="utf-8")

    stale_ts = 1_700_000_000
    fresh_ts = stale_ts + 1_000
    os.utime(stale, (stale_ts, stale_ts))
    os.utime(high_risk, (fresh_ts, fresh_ts))

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == "freshness-policy-block"
    assert "src/core/auth_guard.py" in payload["high_risk_stale_sources"]


def test_docs_generate_allows_high_risk_stale_when_policy_disables_block(
    monkeypatch, tmp_path: Path,
) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    (tmp_path / ".ai" / "policies").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "policies" / "docs_policy.yaml").write_text(
        """
version: v1
freshness:
  warn_stale: true
  block_on_high_risk: false
""",
        encoding="utf-8",
    )
    generated_dir = tmp_path / "docs" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    stale = generated_dir / "codemap.md"
    stale.write_text("old\n", encoding="utf-8")
    high_risk = tmp_path / "src" / "core" / "auth_guard.py"
    high_risk.parent.mkdir(parents=True, exist_ok=True)
    high_risk.write_text("def check() -> bool:\n    return True\n", encoding="utf-8")

    stale_ts = 1_700_000_000
    fresh_ts = stale_ts + 1_000
    os.utime(stale, (stale_ts, stale_ts))
    os.utime(high_risk, (fresh_ts, fresh_ts))

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14"])
    assert result.exit_code == 0
    assert "Freshness policy block" not in result.output


def test_docs_mermaid_command(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    def fake_render(_root: Path, markdown_glob: str, mmdc_bin: str) -> MermaidRenderResult:
        assert markdown_glob == "docs/**/*.md"
        assert mmdc_bin == "mmdc"
        return MermaidRenderResult(
            scanned_files=2,
            diagrams_found=3,
            rendered=3,
            failed=0,
            output_dir=Path("docs/generated/mermaid"),
            generated_paths=[
                Path("docs/generated/mermaid/a.svg"),
                Path("docs/generated/mermaid/b.svg"),
                Path("docs/generated/mermaid/index.md"),
            ],
            index_path=Path("docs/generated/mermaid/index.md"),
            warnings=[],
        )

    monkeypatch.setattr("hast.core.mermaid.render_mermaid_docs", fake_render)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "mermaid"])
    assert result.exit_code == 0
    assert "Markdown scanned: 2" in result.output
    assert "Diagrams found: 3" in result.output
    assert "Rendered: 3" in result.output
    assert "Index: docs/generated/mermaid/index.md" in result.output


def test_docs_mermaid_command_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    def fake_render(_root: Path, markdown_glob: str, mmdc_bin: str) -> MermaidRenderResult:
        return MermaidRenderResult(
            scanned_files=2,
            diagrams_found=3,
            rendered=3,
            failed=0,
            output_dir=Path("docs/generated/mermaid"),
            generated_paths=[
                Path("docs/generated/mermaid/a.svg"),
                Path("docs/generated/mermaid/b.svg"),
                Path("docs/generated/mermaid/index.md"),
            ],
            index_path=Path("docs/generated/mermaid/index.md"),
            warnings=[],
        )

    monkeypatch.setattr("hast.core.mermaid.render_mermaid_docs", fake_render)
    runner = CliRunner()
    result = runner.invoke(main, ["docs", "mermaid", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["diagrams_found"] == 3


def test_docs_sync_vault_command(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "sync-vault"])
    assert result.exit_code == 0
    assert "Vault synced:" in result.output
    assert "Broken wikilinks: 0" in result.output
    assert "Orphan notes: 0" in result.output
    assert (tmp_path / ".knowledge" / "Goal" / "G_DOCS.md").exists()


def test_docs_sync_vault_command_json(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "sync-vault", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["output_dir"] == ".knowledge"
    assert ".knowledge/Goal/G_DOCS.md" in payload["generated_paths"]


def test_docs_sync_vault_strict_fails_on_link_issues(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("hast.cli.find_root", lambda _cwd: tmp_path)
    vault_dir = tmp_path / ".knowledge"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "custom.md").write_text("# custom\n\n[[Goal/MISSING]]\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "sync-vault", "--strict"])
    assert result.exit_code == 1
    assert "vault link checks failed" in result.output
