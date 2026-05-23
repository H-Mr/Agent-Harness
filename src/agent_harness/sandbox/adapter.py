"""Adapter around the ``srt`` sandbox-runtime CLI."""

from __future__ import annotations

import json
import platform as _platform
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _get_platform() -> str:
    """Detect the current platform, distinguishing WSL from Linux."""
    system = _platform.system().lower()
    if system == "linux":
        if "microsoft" in (_platform.release() or "").lower():
            return "wsl"
        return "linux"
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return system


def _supports_sandbox() -> bool:
    """Return True when the current platform can run the sandbox runtime."""
    return _get_platform() in ("linux", "macos", "wsl")


class SandboxUnavailableError(RuntimeError):
    """Raised when sandboxing is required but unavailable."""


@dataclass(frozen=True)
class SandboxAvailability:
    """Computed sandbox-runtime availability for the current environment."""

    enabled: bool
    available: bool
    reason: str | None = None
    command: str | None = None

    @property
    def active(self) -> bool:
        """Return whether sandboxing should be applied to child processes."""
        return self.enabled and self.available


def build_sandbox_runtime_config(sandbox_cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert a sandbox config dict into an ``srt`` settings payload.

    Expects a dict with optional keys:
        network.allowed_domains, network.denied_domains,
        filesystem.allow_read, filesystem.deny_read,
        filesystem.allow_write, filesystem.deny_write.
    """
    network = sandbox_cfg.get("network", {})
    filesystem = sandbox_cfg.get("filesystem", {})
    return {
        "network": {
            "allowedDomains": list(network.get("allowed_domains", [])),
            "deniedDomains": list(network.get("denied_domains", [])),
        },
        "filesystem": {
            "allowRead": list(filesystem.get("allow_read", [])),
            "denyRead": list(filesystem.get("deny_read", [])),
            "allowWrite": list(filesystem.get("allow_write", [])),
            "denyWrite": list(filesystem.get("deny_write", [])),
        },
    }


def get_sandbox_availability(
    enabled: bool = False,
    sandbox_cfg: dict[str, Any] | None = None,
    *,
    fail_if_unavailable: bool = False,
) -> SandboxAvailability:
    """Return whether ``srt`` can be used for the current runtime.

    Parameters
    ----------
    enabled:
        Master flag that controls whether sandboxing is desired.
    sandbox_cfg:
        Optional configuration dict (may contain ``enabled_platforms``).
    fail_if_unavailable:
        When True and sandboxing is required but unavailable, the caller
        should raise ``SandboxUnavailableError`` instead of proceeding.
    """
    if not enabled:
        return SandboxAvailability(enabled=False, available=False, reason="sandbox is disabled")

    platform_name = _get_platform()
    if not _supports_sandbox():
        if platform_name == "windows":
            reason = "sandbox runtime is not supported on native Windows; use WSL for sandboxed execution"
        else:
            reason = f"sandbox runtime is not supported on platform {platform_name}"
        return SandboxAvailability(enabled=True, available=False, reason=reason)

    cfg = sandbox_cfg or {}
    enabled_platforms = {name.lower() for name in cfg.get("enabled_platforms", [])}
    if enabled_platforms and platform_name not in enabled_platforms:
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason=f"sandbox is disabled for platform {platform_name} by configuration",
        )

    srt = shutil.which("srt")
    if not srt:
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason=(
                "sandbox runtime CLI not found; install it with "
                "`npm install -g @anthropic-ai/sandbox-runtime`"
            ),
        )

    if platform_name in {"linux", "wsl"} and shutil.which("bwrap") is None:
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason="bubblewrap (`bwrap`) is required for sandbox runtime on Linux/WSL",
            command=srt,
        )

    if platform_name == "macos" and shutil.which("sandbox-exec") is None:
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason="`sandbox-exec` is required for sandbox runtime on macOS",
            command=srt,
        )

    return SandboxAvailability(enabled=True, available=True, command=srt)


def wrap_command_for_sandbox(
    command: list[str],
    *,
    enabled: bool = False,
    sandbox_cfg: dict[str, Any] | None = None,
    fail_if_unavailable: bool = False,
) -> tuple[list[str], Path | None]:
    """Wrap an argv list with ``srt`` when sandboxing is active.

    Returns
    -------
    A tuple of (possibly-wrapped command list, optional settings file path).
    The caller should delete the settings path when the command completes.
    """
    availability = get_sandbox_availability(
        enabled=enabled,
        sandbox_cfg=sandbox_cfg,
        fail_if_unavailable=fail_if_unavailable,
    )
    if not availability.active:
        if enabled and fail_if_unavailable:
            raise SandboxUnavailableError(availability.reason or "sandbox runtime is unavailable")
        return command, None

    settings_path = _write_runtime_settings(
        build_sandbox_runtime_config(sandbox_cfg or {})
    )
    # The ``srt`` argv form does not reliably preserve child exit codes for shell-style
    # commands such as ``bash -lc 'exit 1'``. Build a single escaped command string and
    # pass it through ``-c`` so hook/tool failures still propagate correctly.
    wrapped = [
        availability.command or "srt",
        "--settings",
        str(settings_path),
        "-c",
        shlex.join(command),
    ]
    return wrapped, settings_path


def _write_runtime_settings(payload: dict[str, Any]) -> Path:
    """Persist a temporary settings file for one sandboxed child process."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="agent-harness-sandbox-",
        suffix=".json",
        delete=False,
    )
    try:
        json.dump(payload, tmp)
        tmp.write("\n")
    finally:
        tmp.close()
    return Path(tmp.name)
