"""AGENTS.md discovery and loading."""

from __future__ import annotations

from pathlib import Path


def discover_agents_md_files(cwd: str | Path) -> list[Path]:
    """Discover AGENTS.md files from *cwd* upward.

    Checks:
      1. AGENTS.md — project instructions
      2. .agents/rules/*.md — project rules directory

    Stops at the filesystem root.
    """
    current = Path(cwd).resolve()
    results: list[Path] = []
    seen: set[Path] = set()

    for directory in [current, *current.parents]:
        candidate = directory / "AGENTS.md"
        if candidate.exists() and candidate not in seen:
            results.append(candidate)
            seen.add(candidate)

        rules_dir = directory / ".agents" / "rules"
        if rules_dir.is_dir():
            for rule in sorted(rules_dir.glob("*.md")):
                if rule not in seen:
                    results.append(rule)
                    seen.add(rule)

        if directory.parent == directory:
            break

    return results


def load_agents_md_prompt(
    cwd: str | Path,
    *,
    max_chars_per_file: int = 12000,
) -> str | None:
    """Load discovered AGENTS.md files into a system prompt section."""
    files = discover_agents_md_files(cwd)
    if not files:
        return None

    lines = ["# Project Instructions"]
    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + "\n...[truncated]..."
        lines.extend(["", f"## {path}", "```md", content.strip(), "```"])
    return "\n".join(lines)
