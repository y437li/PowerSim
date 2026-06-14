#!/usr/bin/env python3
"""gen_nav_index.py — per-folder navigation-index generator.

Walks target source folders and emits a README.md per folder containing:
  (a) a CURATED "## Purpose" block between <!-- curated -->…<!-- /curated -->
      sentinels — PRESERVED across reruns (hand-written prose; never overwritten)
  (b) an AUTO-GENERATED "## Index" block between
      <!-- generated:start -->…<!-- generated:end --> sentinels — always
      regenerated (files → public symbols → one-line docstring / JSDoc).

Usage:
    python scripts/gen_nav_index.py                # all target folders
    python scripts/gen_nav_index.py src/energy_go/env   # single folder
    python scripts/gen_nav_index.py --check        # exit 1 if any index is stale

Stale detection (--check mode):
    Regenerate each folder's index in memory; compare with on-disk content;
    report which folders are stale; exit 1 if any are stale.

Target folders (canonical list):
    src/energy_go/{env,serving,training,harness,generators,telemetry,data,testing,finance}
    src/{components,stores,clients,utils,validators,scene,routes,types,config}
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

TARGET_FOLDERS: list[str] = [
    # Backend — energy_go package
    "src/energy_go/env",
    "src/energy_go/serving",
    "src/energy_go/training",
    "src/energy_go/harness",
    "src/energy_go/generators",
    "src/energy_go/telemetry",
    "src/energy_go/data",
    "src/energy_go/testing",
    "src/energy_go/finance",        # skipped until PR #111 merges
    # Frontend — src/
    "src/components",
    "src/components/live",
    "src/components/training",
    "src/stores",
    "src/clients",
    "src/utils",
    "src/validators",
    "src/scene",
    "src/routes",
    "src/types",
    "src/config",
]

# Sentinel constants (must match exactly on disk)
CURATED_START = "<!-- curated -->"
CURATED_END = "<!-- /curated -->"
GEN_START = "<!-- generated:start -->"
GEN_END = "<!-- generated:end -->"

# Default placeholder when no curated block exists yet
DEFAULT_CURATED_PROSE = (
    "_Purpose not yet documented. Edit the `<!-- curated -->` block in this file to add it._"
)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class SymbolInfo(NamedTuple):
    """One public symbol (function, class, or exported TS identifier)."""

    name: str
    kind: str        # "function" | "class" | "const" | "type" | "interface" | "enum"
    docstring: str   # first non-empty line of docstring / JSDoc; "" if absent


class FileInfo(NamedTuple):
    """Summary of one source file."""

    filename: str       # relative to the folder being indexed
    module_doc: str     # first line of file-level docstring / module comment
    symbols: list       # list[SymbolInfo]


# ---------------------------------------------------------------------------
# Python parser
# ---------------------------------------------------------------------------


def _first_doc_line(node: ast.AST) -> str:
    """Return the first non-empty line of a docstring node, or ""."""
    try:
        raw = ast.get_docstring(node, clean=True) or ""
        for line in raw.splitlines():
            line = line.strip()
            if line:
                return line
    except Exception:
        pass
    return ""


def _is_public(name: str) -> bool:
    """True for names that are part of the public API (not _private)."""
    return not name.startswith("_")


def parse_python_file(path: Path) -> FileInfo:
    """Parse a .py file via AST; extract module doc, public classes/functions."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return FileInfo(filename=path.name, module_doc="[parse error]", symbols=[])

    module_doc = _first_doc_line(tree)

    symbols: list[SymbolInfo] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public(node.name):
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="function",
                        docstring=_first_doc_line(node),
                    )
                )
        elif isinstance(node, ast.ClassDef):
            if _is_public(node.name):
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="class",
                        docstring=_first_doc_line(node),
                    )
                )

    return FileInfo(filename=path.name, module_doc=module_doc, symbols=symbols)


# ---------------------------------------------------------------------------
# TypeScript / TSX parser
# ---------------------------------------------------------------------------

# Match: export [default] (function|class|const|let|var|type|interface|enum) <Name>
# or:    export { Name, ... }
# or:    export type { Name }
_TS_DECL_RE = re.compile(
    r"^export\s+(?:default\s+)?"
    r"(?P<kw>function\*?|class|const|let|var|type|interface|enum)\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
_TS_NAMED_RE = re.compile(
    r"^export\s+(?:type\s+)?\{([^}]+)\}",
    re.MULTILINE,
)
# JSDoc comment immediately preceding an export
_JSDOC_RE = re.compile(r"/\*\*\s*(.*?)\s*\*/\s*$", re.DOTALL)
_JSDOC_LINE_RE = re.compile(r"^[ \t]*\*?\s?(.+)$")


def _extract_jsdoc(source: str, match_start: int) -> str:
    """Extract first sentence from a JSDoc comment that ends just before match_start."""
    preceding = source[:match_start]
    m = _JSDOC_RE.search(preceding)
    if not m:
        return ""
    # Take the first non-empty content line of the JSDoc
    for line in m.group(1).splitlines():
        lm = _JSDOC_LINE_RE.match(line)
        if lm:
            text = lm.group(1).strip()
            if text and not text.startswith("@"):
                return text
    return ""


def _ts_kind(kw: str) -> str:
    kw = kw.rstrip("*")
    if kw in ("const", "let", "var"):
        return "const"
    return kw


def parse_ts_file(path: Path) -> FileInfo:
    """Parse a .ts / .tsx file via regex; extract exported symbols + JSDoc."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return FileInfo(filename=path.name, module_doc="[read error]", symbols=[])

    # Module-level comment: first JSDoc or // comment block at top of file
    module_doc = ""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            cand = stripped.lstrip("/ ").strip()
            if cand:
                module_doc = cand
                break
        elif stripped.startswith("/*"):
            # Grab text after /** or /*
            cand = stripped.lstrip("/* ").strip()
            if cand:
                module_doc = cand
                break
        elif stripped:
            break

    symbols: list[SymbolInfo] = []
    seen: set[str] = set()

    # Named declarations: export function|class|const|type|interface|enum Name
    for m in _TS_DECL_RE.finditer(source):
        name = m.group("name")
        if name in seen:
            continue
        seen.add(name)
        kw = m.group("kw")
        doc = _extract_jsdoc(source, m.start())
        symbols.append(SymbolInfo(name=name, kind=_ts_kind(kw), docstring=doc))

    # Re-export blocks: export { A, B as C }
    for m in _TS_NAMED_RE.finditer(source):
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            # "Name as Alias" → take the exported alias
            parts = item.split(" as ")
            exported_name = parts[-1].strip()
            if exported_name and exported_name not in seen:
                seen.add(exported_name)
                symbols.append(SymbolInfo(name=exported_name, kind="const", docstring=""))

    return FileInfo(filename=path.name, module_doc=module_doc, symbols=symbols)


# ---------------------------------------------------------------------------
# Index rendering
# ---------------------------------------------------------------------------


def _render_symbol_row(s: SymbolInfo) -> str:
    """Format one symbol as a Markdown table row."""
    kind_badge = f"`{s.kind}`"
    doc = s.docstring or "—"
    # Truncate long docstrings in the table
    if len(doc) > 100:
        doc = doc[:97] + "…"
    return f"| `{s.name}` | {kind_badge} | {doc} |"


def render_generated_block(folder: Path, file_infos: list[FileInfo]) -> str:
    """Render the full <!-- generated:start -->…<!-- generated:end --> block."""
    lines: list[str] = [GEN_START, ""]
    lines.append("## Index")
    lines.append("")

    if not file_infos:
        lines.append("_No source files found._")
        lines.append("")
        lines.append(GEN_END)
        return "\n".join(lines)

    for fi in file_infos:
        lines.append(f"### `{fi.filename}`")
        if fi.module_doc:
            lines.append("")
            lines.append(f"> {fi.module_doc}")
        lines.append("")

        if fi.symbols:
            lines.append("| Symbol | Kind | Purpose |")
            lines.append("|--------|------|---------|")
            for s in fi.symbols:
                lines.append(_render_symbol_row(s))
            lines.append("")
        else:
            lines.append("_No public symbols exported._")
            lines.append("")

    lines.append(GEN_END)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# README assembly (preserve curated block, rewrite generated block)
# ---------------------------------------------------------------------------


def _extract_curated_prose(existing_content: str) -> str:
    """Pull the prose body between <!-- curated --> and <!-- /curated --> sentinels.

    The "## Purpose" heading is always re-injected by build_readme, so strip it
    from the extracted content to avoid duplication on re-runs.
    """
    start = existing_content.find(CURATED_START)
    end = existing_content.find(CURATED_END)
    if start == -1 or end == -1 or end <= start:
        return DEFAULT_CURATED_PROSE
    inner = existing_content[start + len(CURATED_START):end].strip()
    # Strip leading "## Purpose" heading if present (added by build_readme)
    if inner.startswith("## Purpose"):
        inner = inner[len("## Purpose"):].strip()
    return inner or DEFAULT_CURATED_PROSE


def build_readme(folder: Path, file_infos: list[FileInfo], existing_content: str = "") -> str:
    """Build the full README.md content for a folder.

    Preserves any existing curated block; regenerates the index block.
    """
    rel = folder.relative_to(REPO_ROOT)
    heading = f"`{rel}`"

    curated_prose = _extract_curated_prose(existing_content)
    generated_block = render_generated_block(folder, file_infos)

    parts = [
        f"# {heading}",
        "",
        CURATED_START,
        "## Purpose",
        "",
        curated_prose,
        CURATED_END,
        "",
        "---",
        "",
        generated_block,
        "",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Folder scanner
# ---------------------------------------------------------------------------


def _collect_source_files(folder: Path) -> list[Path]:
    """Return sorted list of .py / .ts / .tsx files (skip __pycache__ etc.)."""
    files: list[Path] = []
    skip_dirs = {"__pycache__", "node_modules", ".git", "dist", "build"}

    if not folder.is_dir():
        return files

    for p in sorted(folder.iterdir()):
        if p.is_dir() and p.name in skip_dirs:
            continue
        if p.is_file() and p.suffix in {".py", ".ts", ".tsx"}:
            # Skip __init__.py only if it's empty / just a comment
            if p.name == "__init__.py":
                text = p.read_text(encoding="utf-8", errors="ignore").strip()
                # Include __init__.py if it has substantive content (> 3 non-comment lines)
                code_lines = [
                    ln for ln in text.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                if len(code_lines) < 3:
                    continue
            files.append(p)

    return files


def scan_folder(folder: Path) -> list[FileInfo]:
    """Parse all source files in a folder and return FileInfo list."""
    infos: list[FileInfo] = []
    for p in _collect_source_files(folder):
        if p.suffix == ".py":
            infos.append(parse_python_file(p))
        else:
            infos.append(parse_ts_file(p))
    return infos


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


def generate_for_folder(folder: Path, dry_run: bool = False) -> tuple[str, str]:
    """Generate (or check) the README.md for a single folder.

    Returns (path_str, status) where status is "updated", "created", "unchanged",
    or "stale" (only in dry_run mode).
    """
    readme_path = folder / "README.md"
    existing = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    file_infos = scan_folder(folder)
    new_content = build_readme(folder, file_infos, existing_content=existing)

    if dry_run:
        # Only compare the generated block portion
        old_gen = _extract_generated_block(existing)
        new_gen = _extract_generated_block(new_content)
        if old_gen == new_gen:
            return (str(readme_path), "unchanged")
        return (str(readme_path), "stale")

    if new_content == existing:
        return (str(readme_path), "unchanged")

    readme_path.write_text(new_content, encoding="utf-8")
    status = "updated" if existing else "created"
    return (str(readme_path), status)


def _extract_generated_block(content: str) -> str:
    """Extract everything between <!-- generated:start --> and <!-- generated:end -->."""
    start = content.find(GEN_START)
    end = content.find(GEN_END)
    if start == -1 or end == -1:
        return ""
    return content[start:end + len(GEN_END)]


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Usage:
        gen_nav_index.py                       # generate all targets
        gen_nav_index.py src/energy_go/env     # generate one folder
        gen_nav_index.py --check               # check staleness; exit 1 if stale
    """
    if argv is None:
        argv = sys.argv[1:]

    check_mode = "--check" in argv
    folder_args = [a for a in argv if not a.startswith("--")]

    if folder_args:
        targets = [REPO_ROOT / f for f in folder_args]
    else:
        targets = [REPO_ROOT / f for f in TARGET_FOLDERS]

    stale: list[str] = []
    for folder in targets:
        if not folder.exists():
            print(f"  SKIP  {folder} (does not exist yet)")
            continue
        path, status = generate_for_folder(folder, dry_run=check_mode)
        icon = {"unchanged": "  OK   ", "stale": "  STALE", "updated": "  WRITE",
                "created": "  NEW  "}.get(status, "  ?    ")
        print(f"{icon} {path}")
        if status == "stale":
            stale.append(path)

    if check_mode and stale:
        print(f"\n{len(stale)} folder(s) have stale nav-index. Run `python scripts/gen_nav_index.py` to fix.")
        return 1
    if check_mode:
        print("\nAll nav-indexes are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
