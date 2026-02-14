"""Mermaid diagram extraction and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
import subprocess
import tempfile
from typing import Callable


MermaidRenderer = Callable[[str, Path, str], tuple[bool, str | None]]


@dataclass(frozen=True)
class MermaidRenderResult:
    scanned_files: int
    diagrams_found: int
    rendered: int
    failed: int
    output_dir: Path
    generated_paths: list[Path] = field(default_factory=list)
    index_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def extract_mermaid_blocks(markdown: str) -> list[str]:
    """Extract mermaid fenced code blocks from markdown text."""
    pattern = re.compile(r"```mermaid[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    return [match.group(1).strip() for match in pattern.finditer(markdown)]


def render_mermaid_docs(
    root: Path,
    *,
    markdown_glob: str = "docs/**/*.md",
    output_dir: Path | None = None,
    mmdc_bin: str = "mmdc",
    renderer: MermaidRenderer | None = None,
) -> MermaidRenderResult:
    """Render mermaid blocks from markdown files into SVG assets."""
    render_fn = renderer or _render_mermaid_with_mmdc
    resolved_output_dir = output_dir or (root / "docs" / "generated" / "mermaid")
    markdown_files = sorted(path for path in root.glob(markdown_glob) if path.is_file())

    blocks: list[tuple[Path, int, str]] = []
    for path in markdown_files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for idx, block in enumerate(extract_mermaid_blocks(text), start=1):
            blocks.append((path, idx, block))

    warnings: list[str] = []
    generated: list[Path] = []
    rendered = 0
    failed = 0

    if blocks:
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

    tool_missing = False
    for source_path, idx, block in blocks:
        source_rel = _relpath_or_abs(root, source_path)
        target = resolved_output_dir / _diagram_filename(source_rel, idx)
        ok, error = render_fn(block, target, mmdc_bin)
        if ok:
            rendered += 1
            generated.append(target.relative_to(root))
            continue
        failed += 1
        if error:
            warnings.append(f"{source_rel} (diagram {idx}): {error}")
            if "not found" in error.lower():
                tool_missing = True
        if tool_missing:
            break

    if tool_missing and len(blocks) > rendered + failed:
        skipped = len(blocks) - rendered - failed
        warnings.append(f"Skipped remaining diagrams after renderer lookup failure: {skipped}")

    index_path: Path | None = None
    if blocks:
        index_path = resolved_output_dir / "index.md"
        index_path.write_text(
            _render_index(
                root=root,
                markdown_glob=markdown_glob,
                generated_paths=generated,
                diagrams_found=len(blocks),
                rendered=rendered,
                failed=failed,
                warnings=warnings,
            ),
            encoding="utf-8",
        )
        generated.append(index_path.relative_to(root))

    return MermaidRenderResult(
        scanned_files=len(markdown_files),
        diagrams_found=len(blocks),
        rendered=rendered,
        failed=failed,
        output_dir=resolved_output_dir.relative_to(root),
        generated_paths=generated,
        index_path=index_path.relative_to(root) if index_path else None,
        warnings=warnings,
    )


def _diagram_filename(source_rel: str, idx: int) -> str:
    safe_source = source_rel.replace("/", "__").replace(".", "_")
    return f"{safe_source}__d{idx:02d}.svg"


def _render_mermaid_with_mmdc(block: str, output_path: Path, mmdc_bin: str) -> tuple[bool, str | None]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".mmd", delete=False) as fp:
        fp.write(block + "\n")
        input_path = Path(fp.name)
    try:
        proc = subprocess.run(
            [mmdc_bin, "-i", str(input_path), "-o", str(output_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, f"renderer binary not found: {mmdc_bin}"
    finally:
        input_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, err or "mermaid render failed"
    return True, None


def _render_index(
    *,
    root: Path,
    markdown_glob: str,
    generated_paths: list[Path],
    diagrams_found: int,
    rendered: int,
    failed: int,
    warnings: list[str],
) -> str:
    lines = [
        "# Mermaid Render Index",
        "",
        f"- source_glob: `{markdown_glob}`",
        f"- diagrams_found: `{diagrams_found}`",
        f"- rendered: `{rendered}`",
        f"- failed: `{failed}`",
        "",
        "## Generated SVG",
        "",
    ]
    svg_paths = [path for path in generated_paths if path.suffix.lower() == ".svg"]
    if svg_paths:
        for path in svg_paths:
            lines.append(f"- [{path.as_posix()}](../../{path.as_posix()})")
    else:
        lines.append("- (none)")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    lines.append("")
    return "\n".join(lines)


def _relpath_or_abs(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
