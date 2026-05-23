"""Hook execution engine."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agent_harness.hooks.events import HookEvent
from agent_harness.hooks.loader import HookRegistry
from agent_harness.hooks.schemas import (
    AgentHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HttpHookDefinition,
    PromptHookDefinition,
)
from agent_harness.hooks.types import AggregatedHookResult, HookResult
from agent_harness.providers.base import LLMProvider


@dataclass
class HookExecutionContext:
    """Context passed into hook execution."""

    cwd: Path
    provider: LLMProvider | None = None  # for prompt/agent hooks
    default_model: str = ""


class HookExecutor:
    """Execute hooks for lifecycle events."""

    def __init__(self, registry: HookRegistry, context: HookExecutionContext) -> None:
        self._registry = registry
        self._context = context

    def update_registry(self, registry: HookRegistry) -> None:
        """Replace the active hook registry."""
        self._registry = registry

    def update_context(
        self,
        *,
        provider: LLMProvider | None = None,
        default_model: str | None = None,
    ) -> None:
        """Update the active hook execution context."""
        if provider is not None:
            self._context.provider = provider
        if default_model is not None:
            self._context.default_model = default_model

    async def execute(self, event: HookEvent, payload: dict[str, Any]) -> AggregatedHookResult:
        """Execute all matching hooks for an event."""
        results: list[HookResult] = []
        for hook in self._registry.get(event):
            if not _matches_hook(hook, payload):
                continue
            if isinstance(hook, CommandHookDefinition):
                results.append(await self._run_command_hook(hook, event, payload))
            elif isinstance(hook, HttpHookDefinition):
                results.append(await self._run_http_hook(hook, event, payload))
            elif isinstance(hook, PromptHookDefinition):
                results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=False))
            elif isinstance(hook, AgentHookDefinition):
                results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=True))
        return AggregatedHookResult(results=results)

    async def _run_command_hook(
        self,
        hook: CommandHookDefinition,
        event: HookEvent,
        payload: dict[str, Any],
    ) -> HookResult:
        command = _inject_arguments(hook.command, payload, shell_escape=True)
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self._context.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "AGENT_HARNESS_HOOK_EVENT": event.value,
                    "AGENT_HARNESS_HOOK_PAYLOAD": json.dumps(payload),
                },
            )
        except Exception as exc:
            return HookResult(
                hook_type=hook.type,
                success=False,
                blocked=hook.block_on_failure,
                reason=str(exc),
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=hook.timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return HookResult(
                hook_type=hook.type,
                success=False,
                blocked=hook.block_on_failure,
                reason=f"command hook timed out after {hook.timeout_seconds}s",
            )

        output = "\n".join(
            part for part in (
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            ) if part
        )
        success = process.returncode == 0
        return HookResult(
            hook_type=hook.type,
            success=success,
            output=output,
            blocked=hook.block_on_failure and not success,
            reason=output or f"command hook failed with exit code {process.returncode}",
            metadata={"returncode": process.returncode},
        )

    async def _run_http_hook(
        self,
        hook: HttpHookDefinition,
        event: HookEvent,
        payload: dict[str, Any],
    ) -> HookResult:
        try:
            async with httpx.AsyncClient(timeout=hook.timeout_seconds) as client:
                response = await client.post(
                    hook.url,
                    json={"event": event.value, "payload": payload},
                    headers=hook.headers,
                )
            success = response.is_success
            output = response.text
            return HookResult(
                hook_type=hook.type,
                success=success,
                output=output,
                blocked=hook.block_on_failure and not success,
                reason=output or f"http hook returned {response.status_code}",
                metadata={"status_code": response.status_code},
            )
        except Exception as exc:
            return HookResult(
                hook_type=hook.type,
                success=False,
                blocked=hook.block_on_failure,
                reason=str(exc),
            )

    async def _run_prompt_like_hook(
        self,
        hook: PromptHookDefinition | AgentHookDefinition,
        event: HookEvent,
        payload: dict[str, Any],
        *,
        agent_mode: bool,
    ) -> HookResult:
        prompt = _inject_arguments(hook.prompt, payload)
        prefix = (
            "You are validating whether a hook condition passes. "
            'Return strict JSON: {"ok": true} or {"ok": false, "reason": "..."}.'
        )
        if agent_mode:
            prefix += " Be more thorough and reason over the payload before deciding."

        if self._context.provider is None:
            return HookResult(
                hook_type=hook.type,
                success=False,
                blocked=hook.block_on_failure,
                reason="no LLM provider available for prompt/agent hook",
            )

        response = await self._context.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": prefix},
                {"role": "user", "content": prompt},
            ],
            model=hook.model or self._context.default_model,
            max_tokens=512,
        )

        text = response.content or ""
        parsed = _parse_hook_json(text)
        if parsed["ok"]:
            return HookResult(hook_type=hook.type, success=True, output=text)
        return HookResult(
            hook_type=hook.type,
            success=False,
            output=text,
            blocked=hook.block_on_failure,
            reason=parsed.get("reason", "hook rejected the event"),
        )


def _matches_hook(hook: HookDefinition, payload: dict[str, Any]) -> bool:
    matcher = getattr(hook, "matcher", None)
    if not matcher:
        return True
    subject = str(payload.get("tool_name") or payload.get("prompt") or payload.get("event") or "")
    return fnmatch.fnmatch(subject, matcher)


def _inject_arguments(
    template: str, payload: dict[str, Any], *, shell_escape: bool = False
) -> str:
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)
    return template.replace("$ARGUMENTS", serialized)


def _parse_hook_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("ok"), bool):
            return parsed
    except json.JSONDecodeError:
        pass
    lowered = text.strip().lower()
    if lowered in {"ok", "true", "yes"}:
        return {"ok": True}
    return {"ok": False, "reason": text.strip() or "hook returned invalid JSON"}
