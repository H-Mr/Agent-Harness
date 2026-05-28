"""WebSocket channel — full-duplex client connections over ws://."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from llm_harness.core.bus.events import InboundMessage, OutboundMessage
from llm_harness.core.bus.queue import MessageBus
from llm_harness.extensions.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8081

AuthCallback = Callable[[dict[str, Any]], Awaitable[bool]]
"""Auth hook signature: receives the full auth message dict, returns ``True`` to allow."""


class WebSocketChannel(BaseChannel):
    """WebSocket channel for external frontend / API clients.

    Parameters
    ----------
    auth_callback:
        Optional async callable ``(auth_payload: dict) -> bool``.
        When set, every connection must send an ``auth`` message before any
        other message.  The callback receives the full auth JSON dict (which
        must include at least ``sender_id``, ``chat_id``, and whatever
        credentials the SaaS backend requires — token, signature, etc.).
        Return ``True`` to accept, ``False`` to reject.

    Protocol (JSON over text frames):
      Client → Server (first message when *auth_callback* is set)
        ``{"type":"auth", "sender_id":"alice", "chat_id":"c1", "token":"..."}``
      Client → Server
        ``{"type":"message", "content":"Hello"}``
      Server → Client
        ``{"type":"delta","content":"..."}``  — streaming token
        ``{"type":"done","content":"..."}``   — finished turn
        ``{"type":"error","content":"..."}``  — processing error
    """

    name = "websocket"
    display_name = "WebSocket"

    def __init__(self, config: dict | object, bus: MessageBus):
        super().__init__(config, bus)
        if isinstance(config, dict):
            self._host = config.get("host", _DEFAULT_HOST)
            self._port = int(config.get("port", _DEFAULT_PORT))
            self._auth_callback: AuthCallback | None = config.get("auth_callback")
        else:
            self._host = getattr(config, "host", _DEFAULT_HOST)
            self._port = int(getattr(config, "port", _DEFAULT_PORT))
            self._auth_callback = getattr(config, "auth_callback", None)

        # chat_id → WebSocket connection
        self._connections: dict[str, Any] = {}

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        try:
            import websockets
        except ImportError:
            logger.error("websockets library required: pip install websockets")
            return

        async def handler(ws):
            await self._serve(ws)

        self._server = await websockets.serve(
            handler, self._host, self._port,
        )
        logger.info("WebSocket channel listening on ws://%s:%s", self._host, self._port)
        await self._server.wait_closed()

    async def stop(self) -> None:
        self._running = False
        if hasattr(self, "_server") and self._server:
            self._server.close()
        for ws in list(self._connections.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()

    # -- outbound → WebSocket -------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        ws = self._connections.get(msg.chat_id)
        if ws is None:
            return
        await self._safe_send(ws, {"type": "done", "content": msg.content})

    async def send_delta(self, chat_id: str, delta: str, metadata: dict | None = None) -> None:
        ws = self._connections.get(chat_id)
        if ws is None:
            return
        await self._safe_send(ws, {"type": "delta", "content": delta})

    # -- connection handler ---------------------------------------------------

    async def _serve(self, ws) -> None:
        sender_id = ""
        chat_id = ""
        authed = self._auth_callback is None

        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await self._safe_send(ws, {"type": "error", "content": "Invalid JSON"})
                    continue

                msg_type = data.get("type", "")

                if msg_type == "auth":
                    if authed:
                        continue  # already authed, skip duplicate auth
                    if not self._auth_callback:
                        authed = True
                        continue
                    try:
                        if await self._auth_callback(data):
                            authed = True
                            sender_id = str(data.get("sender_id", ""))
                            chat_id = str(data.get("chat_id", ""))
                            self._connections[chat_id] = ws
                            await self._safe_send(ws, {"type": "auth_ok"})
                        else:
                            await self._safe_send(ws, {"type": "error", "content": "Auth denied"})
                            await ws.close()
                            return
                    except Exception as exc:
                        logger.warning("Auth callback raised: %s", exc)
                        await self._safe_send(ws, {"type": "error", "content": "Auth error"})
                        await ws.close()
                        return
                    continue

                if not authed:
                    await self._safe_send(ws, {"type": "error", "content": "Auth required"})
                    continue

                if msg_type == "message":
                    content = str(data.get("content", ""))
                    if not content.strip():
                        continue

                    if chat_id not in self._connections:
                        self._connections[chat_id] = ws

                    await self._handle_message(
                        sender_id=sender_id,
                        chat_id=chat_id,
                        content=content,
                    )

                elif msg_type == "ping":
                    await self._safe_send(ws, {"type": "pong"})

        except Exception:
            logger.debug("WebSocket disconnected: %s", chat_id or "(no session)")
        finally:
            if chat_id:
                self._connections.pop(chat_id, None)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    async def _safe_send(ws, payload: dict) -> None:
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass
