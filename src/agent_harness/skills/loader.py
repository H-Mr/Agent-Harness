"""Skill loading from directories."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agent_harness.skills.types import SkillDefinition


def load_skills_from_dirs(
    directories: Iterable[str | Path] | None,
    *,
    source: str = "user",
) -> list[SkillDefinition]:
    """Load markdown skills from one or more directories.

    Supported layout:

    - ``<root>/<skill-dir>/SKILL.md``
    """
    skills: list[SkillDefinition] = []
    if not directories:
        return skills

    seen: set[Path] = set()
    for directory in directories:
        root = Path(directory).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        candidates: list[Path] = []
        for child in sorted(root.iterdir()):
            if child.is_dir():
                skill_path = child / "SKILL.md"
                if skill_path.exists():
                    candidates.append(skill_path)
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            content = path.read_text(encoding="utf-8")
            default_name = path.parent.name
            name, description = parse_skill_markdown(default_name, content)
            skills.append(
                SkillDefinition(
                    name=name,
                    description=description,
                    content=content,
                    source=source,
                    path=str(path),
                )
            )
    return skills


def parse_skill_markdown(default_name: str, content: str) -> tuple[str, str]:
    """Parse name and description from a skill markdown file with YAML frontmatter support."""
    name = default_name
    description = ""

    lines = content.splitlines()

    # Try YAML frontmatter first (--- ... ---)
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                # Parse frontmatter fields
                for fm_line in lines[1:i]:
                    fm_stripped = fm_line.strip()
                    if fm_stripped.startswith("name:"):
                        val = fm_stripped[5:].strip().strip("'\"")
                        if val:
                            name = val
                    elif fm_stripped.startswith("description:"):
                        val = fm_stripped[12:].strip().strip("'\"")
                        if val:
                            description = val
                break

    # Fallback: extract from headings and first paragraph
    if not description:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                if not name or name == default_name:
                    name = stripped[2:].strip() or default_name
                continue
            if stripped and not stripped.startswith("---") and not stripped.startswith("#"):
                description = stripped[:200]
                break

    if not description:
        description = f"Skill: {name}"
    return name, description
