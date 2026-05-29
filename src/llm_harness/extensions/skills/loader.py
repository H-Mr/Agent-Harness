"""Skill loading — Protocol + default filesystem implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from llm_harness.extensions.skills.types import SkillDefinition, SkillLoader

logger = logging.getLogger(__name__)


def load_skills_from_dirs(
    directories: Iterable[str | Path] | None,
    *,
    source: str = "user",
) -> list[SkillDefinition]:
    """Convenience — load skills from directories synchronously."""
    if not directories:
        return []
    return DirectorySkillLoader(directories, source=source).load_sync()


class DirectorySkillLoader:
    """Default :class:`SkillLoader` implementation — scans directories for ``<name>/SKILL.md``.

    Usage::

        loader = DirectorySkillLoader(["./skills", "/opt/skills"])
        skills = await loader.load()
    """

    def __init__(
        self,
        directories: Iterable[str | Path],
        *,
        source: str = "user",
    ) -> None:
        self._directories = list(directories)
        self._source = source

    def load_sync(self) -> list[SkillDefinition]:
        """Synchronous convenience for filesystem-backed loading."""
        return self._scan()

    async def load(self) -> list[SkillDefinition]:
        """Async loader (compatible with :class:`SkillLoader` Protocol)."""
        return self._scan()

    def _scan(self) -> list[SkillDefinition]:
        skills: list[SkillDefinition] = []
        seen: set[Path] = set()

        for directory in self._directories:
            root = Path(directory).expanduser().resolve()
            if not root.exists():
                logger.warning("Skill directory '%s' does not exist, skipping", root)
                continue
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
                name, description = parse_skill_markdown(path.parent.name, content)
                skills.append(
                    SkillDefinition(
                        name=name,
                        description=description,
                        content=content,
                        source=self._source,
                        path=str(path),
                    )
                )
        return skills


def parse_skill_markdown(default_name: str, content: str) -> tuple[str, str]:
    """Parse name and description from a SKILL.md file.

    Supports YAML frontmatter (``---`` delimited), with fallback to
    Markdown heading and first paragraph.
    """
    name = default_name
    description = ""

    lines = content.splitlines()

    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
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
