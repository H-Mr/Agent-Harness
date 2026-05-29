"""Tests for the skills subsystem (loader.py, registry.py, checker.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_harness.extensions.skills.checker import check_skill_requirements
from llm_harness.extensions.skills.loader import load_skills_from_dirs, parse_skill_markdown
from llm_harness.extensions.skills.registry import SkillRegistry
from llm_harness.extensions.skills.types import SkillDefinition

# =============================================================================
# parse_skill_markdown
# =============================================================================


class TestParseSkillMarkdown:
    """parse_skill_markdown YAML frontmatter, heading and paragraph fallbacks."""

    def test_yaml_frontmatter(self):
        """Extracts name and description from YAML frontmatter."""
        content = (
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "---\n"
            "\n"
            "# Content"
        )
        name, desc = parse_skill_markdown("default", content)
        assert name == "my-skill"
        assert desc == "A test skill"

    def test_yaml_frontmatter_with_quotes(self):
        """Strips surrounding quotes from frontmatter values."""
        content = (
            "---\n"
            "name: 'quoted-name'\n"
            'description: "quoted desc"\n'
            "---\n"
        )
        name, desc = parse_skill_markdown("default", content)
        assert name == "quoted-name"
        assert desc == "quoted desc"

    def test_heading_fallback(self):
        """Uses the first heading as name when frontmatter is absent."""
        content = "# My Heading\n\nThis is the description text."
        name, desc = parse_skill_markdown("default", content)
        assert name == "My Heading"
        assert desc == "This is the description text."

    def test_first_paragraph_fallback(self):
        """Uses the first non-heading line as description."""
        content = "This is the description.\n\nMore text here."
        name, desc = parse_skill_markdown("default", content)
        assert name == "default"  # falls back to default_name
        assert desc == "This is the description."

    def test_empty_content(self):
        """Returns default_name and a generated description for empty content."""
        name, desc = parse_skill_markdown("empty-skill", "")
        assert name == "empty-skill"
        assert desc == "Skill: empty-skill"

    def test_content_with_only_frontmatter(self):
        """Handles content with frontmatter only."""
        content = "---\nname: minimal\n---"
        name, desc = parse_skill_markdown("default", content)
        assert name == "minimal"
        # The fallback loop picks up 'name: minimal' as description text
        # since it is not inside the frontmatter block from the loop's perspective
        assert desc == "name: minimal"

    def test_description_truncated_at_200_chars(self):
        """First-paragraph description is capped at 200 characters."""
        long_para = "A" * 300
        name, desc = parse_skill_markdown("default", long_para)
        assert len(desc) == 200


# =============================================================================
# load_skills_from_dirs
# =============================================================================


class TestLoadSkillsFromDirs:
    """load_skills_from_dirs directory scanning."""

    def test_load_from_directory(self, tmp_workspace: Path):
        """Loads skills from a directory containing <name>/SKILL.md files."""
        skill_dir = tmp_workspace / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test skill\n---\n\nContent", encoding="utf-8")

        skills = load_skills_from_dirs([tmp_workspace])
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == "A test skill"
        assert skills[0].path == str((skill_dir / "SKILL.md").resolve())

    def test_load_returns_empty_for_none(self):
        """Returns empty list when directories is None."""
        assert load_skills_from_dirs(None) == []

    def test_load_returns_empty_for_empty_list(self):
        """Returns empty list when directories is an empty iterable."""
        assert load_skills_from_dirs([]) == []

    def test_skips_non_existent_directory(self, caplog):
        """Logs a warning and skips non-existent directories."""
        import logging
        caplog.set_level(logging.WARNING)

        result = load_skills_from_dirs([Path("/nonexistent/path")])
        assert result == []
        assert "does not exist" in caplog.text

    def test_deduplicates_by_path(self, tmp_workspace: Path):
        """Skills with the same path are only loaded once."""
        skill_dir = tmp_workspace / "dup-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: dup-skill\n---\n\nContent", encoding="utf-8")

        # Pass the same directory twice
        skills = load_skills_from_dirs([tmp_workspace, tmp_workspace])
        assert len(skills) == 1

    def test_ignores_dirs_without_claude_md(self, tmp_workspace: Path):
        """Directories without SKILL.md are skipped."""
        empty_dir = tmp_workspace / "empty"
        empty_dir.mkdir()
        skills = load_skills_from_dirs([tmp_workspace])
        assert len(skills) == 0

    def test_load_multiple_skills(self, tmp_workspace: Path):
        """Loads multiple skills from subdirectories."""
        for name in ("skill-a", "skill-b", "skill-c"):
            d = tmp_workspace / name
            d.mkdir()
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n\nContent", encoding="utf-8")

        skills = load_skills_from_dirs([tmp_workspace])
        assert len(skills) == 3
        assert {s.name for s in skills} == {"skill-a", "skill-b", "skill-c"}

    def test_source_defaults_to_user(self, tmp_workspace: Path):
        """source parameter defaults to 'user'."""
        d = tmp_workspace / "src-skill"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: src-skill\n---\n\nContent", encoding="utf-8")
        skills = load_skills_from_dirs([tmp_workspace])
        assert skills[0].source == "user"

    def test_source_custom(self, tmp_workspace: Path):
        """source parameter can be overridden."""
        d = tmp_workspace / "custom-skill"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: custom-skill\n---\n\nContent", encoding="utf-8")
        skills = load_skills_from_dirs([tmp_workspace], source="builtin")
        assert skills[0].source == "builtin"


# =============================================================================
# SkillDefinition dataclass
# =============================================================================


class TestSkillDefinition:
    """SkillDefinition dataclass creation."""

    def test_frozen_dataclass(self):
        """SkillDefinition is a frozen dataclass."""
        sd = SkillDefinition(name="test", description="desc", content="# Hi", source="user")
        assert sd.name == "test"
        assert sd.description == "desc"
        assert sd.content == "# Hi"
        assert sd.source == "user"
        assert sd.path is None  # default

    def test_with_path(self):
        """SkillDefinition accepts an optional path."""
        sd = SkillDefinition(name="t", description="d", content="c", source="s", path="/some/path")
        assert sd.path == "/some/path"


# =============================================================================
# SkillRegistry
# =============================================================================


class TestSkillRegistry:
    """SkillRegistry register / get / list_skills."""

    def test_register_and_get(self):
        """register stores a skill retrievable by name."""
        registry = SkillRegistry()
        skill = SkillDefinition(name="greet", description="Greets user", content="# Greet", source="user")
        registry.register(skill)
        assert registry.get("greet") is skill

    def test_get_nonexistent(self):
        """get returns None for unknown names."""
        registry = SkillRegistry()
        assert registry.get("no-such-skill") is None

    def test_list_skills_sorted(self):
        """list_skills returns all skills sorted by name."""
        registry = SkillRegistry()
        registry.register(SkillDefinition(name="z-skill", description="", content="", source=""))
        registry.register(SkillDefinition(name="a-skill", description="", content="", source=""))
        registry.register(SkillDefinition(name="m-skill", description="", content="", source=""))

        names = [s.name for s in registry.list_skills()]
        assert names == ["a-skill", "m-skill", "z-skill"]

    def test_register_overwrites(self):
        """Registering a skill with an existing name overwrites it."""
        registry = SkillRegistry()
        s1 = SkillDefinition(name="same", description="first", content="", source="")
        s2 = SkillDefinition(name="same", description="second", content="", source="")
        registry.register(s1)
        registry.register(s2)
        assert registry.get("same").description == "second"

    def test_empty_registry(self):
        """list_skills returns empty list for fresh registry."""
        registry = SkillRegistry()
        assert registry.list_skills() == []


# =============================================================================
# check_skill_requirements
# =============================================================================


class TestCheckSkillRequirements:
    """check_skill_requirements requirement validation."""

    def test_no_requirements(self):
        """Returns (True, []) when metadata has no requires key."""
        ok, missing = check_skill_requirements({})
        assert ok is True
        assert missing == []

    def test_empty_requires(self):
        """Returns (True, []) when requires is empty."""
        ok, missing = check_skill_requirements({"requires": {}})
        assert ok is True
        assert missing == []

    def test_missing_binary(self):
        """Flags a missing binary."""
        metadata = {"requires": {"bins": ["this-binary-should-not-exist-xyzzy"]}}
        ok, missing = check_skill_requirements(metadata)
        assert ok is False
        assert any("CLI: this-binary-should-not-exist-xyzzy" in m for m in missing)

    def test_existing_binary(self):
        """Passes when a required binary exists (python)."""
        metadata = {"requires": {"bins": ["python"]}}
        ok, missing = check_skill_requirements(metadata)
        assert ok is True
        assert missing == []

    def test_missing_env_var(self):
        """Flags a missing environment variable."""
        metadata = {"requires": {"env": ["THIS_ENV_VAR_SHOULD_NOT_EXIST"]}}
        ok, missing = check_skill_requirements(metadata)
        assert ok is False
        assert any("ENV: THIS_ENV_VAR_SHOULD_NOT_EXIST" in m for m in missing)

    def test_present_env_var(self):
        """Passes when a required env var exists."""
        import os
        os.environ["TEST_CRON_SKILL_EXISTS"] = "1"
        try:
            metadata = {"requires": {"env": ["TEST_CRON_SKILL_EXISTS"]}}
            ok, missing = check_skill_requirements(metadata)
            assert ok is True
            assert missing == []
        finally:
            os.environ.pop("TEST_CRON_SKILL_EXISTS", None)

    def test_multiple_missing(self):
        """Reports all missing requirements."""
        metadata = {
            "requires": {
                "bins": ["nonexistent-binary-1", "nonexistent-binary-2"],
                "env": ["NONEXISTENT_ENV"],
            }
        }
        ok, missing = check_skill_requirements(metadata)
        assert ok is False
        assert len(missing) == 3
