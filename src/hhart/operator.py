from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable, Iterable, Mapping

from hhart.contract import Contract

logger = logging.getLogger(__name__)

CLOSED = ("ConnectionClosed", "ConnectionClosedOK", "ConnectionClosedError")


async def serve(ws, contract: Contract, publisher, handlers: Mapping[str, Callable[[object], Awaitable]], *,
                reject: Callable[[str], dict], snapshot: Callable[[], Iterable[dict]] = tuple,
                moves: Mapping[str, bool] | None = None,
                on_leave: Callable[[], Awaitable] | None = None) -> None:
    """
    ws: anything with send() you can async-iterate. handlers: command name -> async fn(message). moves: 
    whether each command leaves the robot moving. If it's still moving when the client goes, on_leave runs.
    """
    moving = False
    publisher.add(ws)
    try:
        await ws.send(json.dumps(contract.describe()))
        for message in snapshot():
            await ws.send(json.dumps(message))
        async for raw in ws:
            name, error = await _handle(raw, contract, handlers)
            if error is not None:
                await ws.send(json.dumps(reject(error)))
            elif moves and name in moves:
                moving = moves[name]
    except Exception as exc:
        if type(exc).__name__ not in CLOSED:
            logger.warning("operator connection: %s", exc)
    finally:
        publisher.discard(ws)
        if moving and on_leave is not None:
            logger.info("operator left while the robot moved: stopping")
            await on_leave()


async def _handle(raw, contract: Contract, handlers) -> tuple[str | None, str | None]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, "invalid JSON"
    name = data.get("type") if isinstance(data, dict) else None
    message = contract.decode(data)
    handler = handlers.get(name)
    if message is None or handler is None:
        return name, f"not a command this robot accepts: {name!r}"
    try:
        await handler(message)
    except ValueError as exc:
        return name, str(exc)
    return name, None
