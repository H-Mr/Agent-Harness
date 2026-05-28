"""Launcher — assembles Harness + Agent + Channels and runs the message loop."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

from llm_harness.adapters.providers.base import LLMProvider
from llm_harness.adapters.providers.registry import detect_provider, instantiate_provider
from llm_harness.config.schema import MemoryConfig
from llm_harness.config.loader import load_config
from llm_harness.config.schema import Config
from llm_harness.core.harness import Harness
from llm_harness.extensions.channels.base import BaseChannel
from llm_harness.extensions.channels.manager import ChannelManager

logger = logging.getLogger(__name__)


async def launch(
    *,
    provider: LLMProvider | None = None,
    channels: dict[str, type[BaseChannel]] | None = None,
    config: str | Path | Config | None = None,
    workspace: str | Path = ".",
    model: str = "",
    **kwargs: Any,
) -> None:
    """Start the llm-harness service.

    Assembles Harness → Agent → Channels → starts the message processing loop.
    Runs until a shutdown signal (SIGINT / SIGTERM) is received.

    Parameters
    ----------
    provider:
        LLM provider instance.  If ``None``, auto-detected from *model*.
    channels:
        Mapping of channel name → ``BaseChannel`` subclass, e.g.
        ``{"telegram": TelegramChannel, "cli": CLIChennel}``.
    config:
        Path to a YAML config file, or a pre-built ``Config`` object.
    workspace:
        Root directory for the multi-tenant workspace tree.
    model:
        Model identifier used when *provider* is ``None``.
    **kwargs:
        Passed through to :class:`Harness` as overrides.
    """
    # ── resolve config ──────────────────────────────────────────────
    if config is None:
        cfg = Config()
    elif isinstance(config, Config):
        cfg = config
    else:
        cfg = load_config(config, model=model or None)

    workspace_path = Path(workspace).expanduser().resolve()
    if str(cfg.workspace) != ".":
        workspace_path = cfg.workspace_path

    # ── resolve provider ────────────────────────────────────────────
    if provider is None:
        model_name = model or cfg.agent.model
        spec = detect_provider(model_name)
        if spec is None:
            raise RuntimeError(f"Cannot detect provider for model: {model_name}")
        provider = instantiate_provider(spec)

    # ── assemble harness + agent ────────────────────────────────────
    harness = Harness(
        provider=provider,
        model=model or cfg.agent.model,
        workspace=workspace_path,
        tools=kwargs.pop("tools", None) or cfg.tools.enabled,
        permissions=kwargs.pop("permissions", cfg.permission.mode),
        memory=kwargs.pop("memory", None) or _resolve_memory_url(cfg.memory, workspace_path),
        sandbox=kwargs.pop("sandbox", "srt"),
        swarm=kwargs.pop("swarm", None),
        sessions=kwargs.pop("sessions", None),
        observability=kwargs.pop("observability", None),
        context_window_tokens=kwargs.pop("context_window_tokens", cfg.agent.context_window_tokens),
        max_completion_tokens=kwargs.pop("max_completion_tokens", cfg.agent.max_tokens),
        **kwargs,
    )
    agent = harness.create_agent()

    # ── start channels ──────────────────────────────────────────────
    channel_mgr: ChannelManager | None = None
    if channels:
        channel_configs: dict[str, Any] = {}
        for ch in cfg.channels:
            channel_configs[ch.type] = ch.settings
        channel_mgr = ChannelManager(
            channel_types=channels,
            channels_config=channel_configs,
            bus=harness.bus,
        )
        asyncio.create_task(channel_mgr.start_all())
        logger.info("Channels started: %s", list(channels.keys()))

    # ── shutdown handler ────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _on_shutdown() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_shutdown)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    # ── main loop ───────────────────────────────────────────────────
    logger.info("llm-harness v0.1.0 — model=%s, workspace=%s", harness.model, harness.workspace)

    while not shutdown_event.is_set():
        try:
            msg = await asyncio.wait_for(
                harness.bus.consume_inbound(), timeout=1.0,
            )
            result = await agent.process(msg)
            if result:
                await harness.bus.publish_outbound(result)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in message loop")

    # ── graceful shutdown ───────────────────────────────────────────
    logger.info("Shutting down...")
    if channel_mgr:
        await channel_mgr.stop_all()
    logger.info("llm-harness stopped")


def _resolve_memory_url(cfg: MemoryConfig, workspace_path) -> str:
    """Convert MemoryConfig to a Harness-compatible URL string."""
    if cfg.backend == "file":
        return f"file://{workspace_path}"
    if cfg.backend == "tencentdb":
        return "tencentdb://" + cfg.base_url.replace("http://", "").replace("https://", "")
    return cfg.backend
