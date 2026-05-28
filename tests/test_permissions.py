"""Tests for PermissionChecker: sensitive path protection, path rules, command deny."""

import pytest
from llm_harness.core.permissions.checker import PermissionChecker, PermissionDecision
from llm_harness.core.permissions.settings import PermissionSettings
from llm_harness.core.permissions.modes import PermissionMode


class TestSensitivePaths:
    """Built-in SENSITIVE_PATH_PATTERNS must always block access."""

    def test_blocks_ssh_key(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        result = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/.ssh/id_rsa")
        assert not result.allowed
        assert "sensitive credential" in result.reason

    def test_blocks_aws_credentials(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        result = checker.evaluate("read_file", is_read_only=True, file_path="/root/.aws/credentials")
        assert not result.allowed

    def test_blocks_kube_config(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        result = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/.kube/config")
        assert not result.allowed

    def test_allows_normal_path(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        result = checker.evaluate("read_file", is_read_only=True, file_path="/home/user/readme.txt")
        assert result.allowed

    def test_no_file_path_bypasses_sensitive_check(self):
        """When file_path is None, sensitive check is skipped (no false positive)."""
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        result = checker.evaluate("exec", is_read_only=False, command="ls")
        assert result.allowed  # FULL_AUTO allows, but sensitive check skipped


class TestCommandDeny:
    """Command deny patterns must block dangerous commands."""

    def test_denies_dangerous_command(self):
        settings = PermissionSettings(mode=PermissionMode.FULL_AUTO, denied_commands=["rm -rf /*"])
        checker = PermissionChecker(settings)
        result = checker.evaluate("exec", is_read_only=False, command="rm -rf /")
        assert not result.allowed

    def test_allows_safe_command(self):
        settings = PermissionSettings(mode=PermissionMode.FULL_AUTO, denied_commands=["rm -rf /*"])
        checker = PermissionChecker(settings)
        result = checker.evaluate("exec", is_read_only=False, command="ls -la")
        assert result.allowed


class TestPathRules:
    """User-defined path rules must allow/deny based on glob patterns."""

    def test_deny_rule_blocks_path(self):
        settings = PermissionSettings(
            mode=PermissionMode.FULL_AUTO,
            path_rules=[{"pattern": "/etc/*", "allow": False}],
        )
        checker = PermissionChecker(settings)
        result = checker.evaluate("read_file", is_read_only=True, file_path="/etc/passwd")
        assert not result.allowed

    def test_rule_without_file_path_does_not_match(self):
        settings = PermissionSettings(
            mode=PermissionMode.FULL_AUTO,
            path_rules=[{"pattern": "/etc/*", "allow": False}],
        )
        checker = PermissionChecker(settings)
        result = checker.evaluate("exec", is_read_only=False, command="echo hello")
        assert result.allowed  # no file_path, so path rules don't apply


class TestDeniedTools:
    """Explicitly denied tools must be blocked."""

    def test_denied_tool_blocked(self):
        settings = PermissionSettings(denied_tools=["exec"])
        checker = PermissionChecker(settings)
        result = checker.evaluate("exec", is_read_only=False)
        assert not result.allowed

    def test_allowed_tool_bypasses_deny(self):
        settings = PermissionSettings(allowed_tools=["exec"])
        checker = PermissionChecker(settings)
        result = checker.evaluate("exec", is_read_only=False)
        assert result.allowed


class TestPermissionModes:
    """Permission modes must control tool access."""

    def test_default_mode_requires_confirmation_for_mutating(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))
        result = checker.evaluate("write_file", is_read_only=False)
        assert not result.allowed
        assert result.requires_confirmation

    def test_default_mode_allows_read_only(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.DEFAULT))
        result = checker.evaluate("read_file", is_read_only=True)
        assert result.allowed

    def test_full_auto_allows_all(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO))
        result = checker.evaluate("write_file", is_read_only=False)
        assert result.allowed

    def test_plan_mode_blocks_mutating(self):
        checker = PermissionChecker(PermissionSettings(mode=PermissionMode.PLAN))
        result = checker.evaluate("write_file", is_read_only=False)
        assert not result.allowed
        assert not result.requires_confirmation
