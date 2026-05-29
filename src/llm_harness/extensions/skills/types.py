"""Skill data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SkillDefinition:
    """A loaded skill."""

    name: str
    description: str
    content: str
    source: str
    path: str | None = None


@runtime_checkable
class SkillLoader(Protocol):
    """Protocol for loading skills from any source.

    Implement this to load skills from a database, API, S3 bucket, or
    any other source.  The built-in :class:`DirectorySkillLoader` handles
    the common filesystem case.
    """

    async def load(self) -> list[SkillDefinition]:
        """Return all available skills."""
        ...
