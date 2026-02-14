"""Tests for mermaid rendering helpers."""

from __future__ import annotations

from pathlib import Path

from devf.core.mermaid import extract_mermaid_blocks, render_mermaid_docs


def test_extract_mermaid_blocks() -> None:
    markdown = """
# Doc

```mermaid
graph TD
  A-->B
```

```python
print("hi")
```

```mermaid
sequenceDiagram
  A->>B: ping
```
"""
    blocks = extract_mermaid_blocks(markdown)
    assert len(blocks) == 2
    assert "graph TD" in blocks[0]
    assert "sequenceDiagram" in blocks[1]


def test_render_mermaid_docs_with_fake_renderer(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "arch.md").write_text(
        """
# Architecture
```mermaid
graph TD
  A-->B
```

```mermaid
graph TD
  B-->C
```
""",
        encoding="utf-8",
    )

    def fake_renderer(block: str, output_path: Path, _mmdc: str) -> tuple[bool, str | None]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"<svg><!-- {block[:12]} --></svg>", encoding="utf-8")
        return True, None

    result = render_mermaid_docs(
        tmp_path,
        markdown_glob="docs/**/*.md",
        renderer=fake_renderer,
    )
    assert result.scanned_files == 1
    assert result.diagrams_found == 2
    assert result.rendered == 2
    assert result.failed == 0
    assert result.index_path is not None
    assert (tmp_path / result.index_path).exists()
    assert len(result.generated_paths) == 3  # 2 svg + index.md


def test_render_mermaid_docs_renderer_missing(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "arch.md").write_text(
        """
```mermaid
graph TD
  A-->B
```
""",
        encoding="utf-8",
    )

    def missing_renderer(_block: str, _output_path: Path, _mmdc: str) -> tuple[bool, str | None]:
        return False, "renderer binary not found: mmdc"

    result = render_mermaid_docs(
        tmp_path,
        markdown_glob="docs/**/*.md",
        renderer=missing_renderer,
    )
    assert result.diagrams_found == 1
    assert result.rendered == 0
    assert result.failed == 1
    assert result.warnings
    assert "renderer binary not found" in result.warnings[0]
