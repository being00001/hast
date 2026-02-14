"""CLI tests for docs commands."""

from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from devf.cli import main
from devf.core.mermaid import MermaidRenderResult


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
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "generate", "--window", "14"])
    assert result.exit_code == 0
    assert "Generated docs: 4 file(s)" in result.output
    assert "Mermaid diagrams:" in result.output
    assert (tmp_path / "docs" / "generated" / "codemap.md").exists()


def test_docs_generate_warns_when_stale(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)
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


def test_docs_mermaid_command(monkeypatch, tmp_path: Path) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr("devf.cli.find_root", lambda _cwd: tmp_path)

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

    monkeypatch.setattr("devf.core.mermaid.render_mermaid_docs", fake_render)

    runner = CliRunner()
    result = runner.invoke(main, ["docs", "mermaid"])
    assert result.exit_code == 0
    assert "Markdown scanned: 2" in result.output
    assert "Diagrams found: 3" in result.output
    assert "Rendered: 3" in result.output
    assert "Index: docs/generated/mermaid/index.md" in result.output
