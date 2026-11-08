from __future__ import annotations

import asyncio
import json

# Closing client would otherwise stall every publish for 10 s close timeout
SEND_TIMEOUT_S = 0.5


class WebSocketPublisher:
    def __init__(self) -> None:
        self._clients: set = set()

    def add(self, client) -> None:
        self._clients.add(client)

    def discard(self, client) -> None:
        self._clients.discard(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def publish(self, message: dict) -> None:
        clients = list(self._clients)
        if not clients:
            return
        payload = json.dumps(message)
        results = await asyncio.gather(
            *(asyncio.wait_for(c.send(payload), SEND_TIMEOUT_S) for c in clients),
            return_exceptions=True)
        for client, result in zip(clients, results):
            if isinstance(result, Exception):
                self._clients.discard(client)
