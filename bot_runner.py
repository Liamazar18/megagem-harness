"""Persistent spawned bot workers, bounded calls, and last-successful checkpoints.

Snapshots travel to workers as pickle. Workers return JSON primitives and opaque
checkpoint bytes; the game process never unpickles data produced by a bot.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
import math
import multiprocessing
import pickle
import random
import socket
import struct
import sys
import time
from multiprocessing.process import BaseProcess
from types import TracebackType
from typing import Any

from bots import Bot

# Create the module logger for worker errors and timeouts.
logger = logging.getLogger(__name__)
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
CALLBACKS = frozenset(
    {"on_game_start", "get_bid", "choose_hidden_gem", "on_round_end", "on_game_end"}
)


# Return a monotonic deadline, or None when timeouts are disabled.
def _deadline(timeout: float | None) -> float | None:
    return None if timeout is None else time.monotonic() + timeout


# Limit each socket operation to the remaining time budget.
def _set_timeout(channel: socket.socket, deadline: float | None) -> None:
    if deadline is None:
        channel.settimeout(None)
    else:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Bot call exceeded its time budget")
        channel.settimeout(remaining)


# Send a length-prefixed JSON message within the remaining time budget.
def _send(
    channel: socket.socket, message: dict[str, Any], deadline: float | None
) -> None:
    payload = json.dumps(message).encode()
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Bot message or checkpoint exceeds the 16 MiB limit")
    _set_timeout(channel, deadline)
    # Send the complete frame, or raise if the connection fails or times out.
    channel.sendall(struct.pack("!I", len(payload)) + payload)


# Read exactly size bytes without resetting the overall deadline.
def _read_exact(channel: socket.socket, size: int, deadline: float | None) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        _set_timeout(channel, deadline)
        chunk = channel.recv(min(size - len(chunks), 65536))
        if not chunk:
            raise EOFError("Bot worker disconnected")
        chunks.extend(chunk)
    return bytes(chunks)


# Read the four-byte message length, then decode the JSON payload.
def _receive(channel: socket.socket, deadline: float | None) -> dict[str, Any]:
    # Read the message length from the four-byte header.
    size = struct.unpack("!I", _read_exact(channel, 4, deadline))[0]
    if size > MAX_MESSAGE_BYTES:
        raise ValueError("Bot message or checkpoint exceeds the 16 MiB limit")
    # Read and decode the complete payload.
    message = json.loads(_read_exact(channel, size, deadline))
    if not isinstance(message, dict):
        raise ValueError("Expected a bot message object")
    return message


# Pickle a Python object and encode the bytes as Base64 text.
def _encode(value: object) -> str:
    return base64.b64encode(pickle.dumps(value)).decode("ascii")


# Decode Base64 text and unpickle the resulting bytes inside a worker.
def _decode(value: str) -> Any:
    # Called only inside workers, never on bot-produced data in the game process.
    return pickle.loads(base64.b64decode(value))


# Save bot memory and the worker's private random-module state.
def _checkpoint(bot: Bot) -> str:
    return _encode((bot.save_state(), random.getstate()))


# Run the bot callbacks in a separate process and return completed checkpoints.
def _worker(
    channel: socket.socket,  # Worker endpoint of the connection to the parent.
    module: str,  # Importable module containing the bot class.
    qualname: str,  # Qualified class name within the module.
    checkpoint: str | None,  # Last completed checkpoint, if available.
    seed: int | None,  # Independent seed for the worker's random module.
    timeout: float | None,  # Callback allowance in seconds; None disables the limit.
) -> None:
    try:
        # multiprocessing inherits argv; bot callbacks do not need host CLI seeds.
        sys.argv = ["megagem-bot"]
        # Import the module containing the bot class.
        bot_class: Any = importlib.import_module(module)
        # Resolve the class through its qualified name.
        for part in qualname.split("."):
            bot_class = getattr(bot_class, part)
        # Verify that the resolved class inherits from Bot.
        if not isinstance(bot_class, type) or not issubclass(bot_class, Bot):
            raise TypeError("Bot class must inherit from Bot")
        # Seed the worker's private random module.
        random.seed(seed)
        if checkpoint is None:
            # Construct a fresh bot when no checkpoint exists.
            bot = bot_class()
        else:
            # Restore bot memory and private random state from the checkpoint.
            # Allocate the instance without calling __init__.
            bot = bot_class.__new__(bot_class)
            state, rng_state = _decode(checkpoint)
            bot.load_state(state)
            random.setstate(rng_state)
        # Expose the callback allowance; the parent enforces the timeout.
        bot.timeout_seconds = timeout
        # Confirm startup and send an initial checkpoint to the parent.
        _send(channel, {"ok": True, "checkpoint": _checkpoint(bot)}, None)
        while True:
            # Wait for the next callback request.
            request = _receive(channel, None)
            method = request["method"]
            # Reject requests for methods outside the callback interface.
            if method not in CALLBACKS:
                raise ValueError("Unknown bot callback")
            try:
                args = _decode(request["args"])
                # Invoke the requested callback with the decoded arguments.
                result = getattr(bot, method)(*args)
                # Forward only integer decisions or None as JSON values.
                # Never send arbitrary return objects for the parent to unpickle.
                value = result if type(result) is int else None
                # Send the result and checkpoint; the parent keeps the checkpoint
                # opaque.
                _send(
                    channel,
                    {"ok": True, "value": value, "checkpoint": _checkpoint(bot)},
                    None,
                )
            except Exception as exc:
                # Report the error to the parent.
                _send(
                    channel,
                    {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                    None,
                )
    except (EOFError, OSError):
        pass
    except Exception as exc:
        # Report the error to the parent.
        try:
            _send(channel, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, None)
        except (OSError, ValueError):
            pass
    finally:
        # Close the worker's socket when this function exits.
        channel.close()


# Manage a bot worker, invoke callbacks, and retain completed checkpoints.
class BotRunner:
    """Own one bot's worker and memory; can be reused across multiple games.

    Callback time includes argument transport and checkpointing. Worker startup
    has a separate allowance of at least five seconds, or no limit with None.
    """

    def __init__(
        self,
        bot_class: type[Bot] = Bot,  # An importable Bot subclass, not a bot instance.
        *,
        timeout: float | None = 1.0,
        seed: int | None = None,
    ) -> None:
        # Validate the bot class and timeout configuration.
        if not issubclass(bot_class, Bot):
            raise TypeError("Bot class must inherit from Bot")
        if "<locals>" in bot_class.__qualname__ or bot_class.__module__ == "__main__":
            raise ValueError("Define bot classes in an importable module")
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Bot timeout must be positive and finite, or None")
        self.bot_class = bot_class
        self.timeout = timeout
        self.seed = seed
        # Player replaces this label with one that includes the player ID.
        self.label = bot_class.__name__
        self.last_error: str | None = None
        self._checkpoint: str | None = None
        self._process: BaseProcess | None = None
        self._channel: socket.socket | None = None

    # Start a worker process and establish its connection to the parent.
    def _start(self) -> None:
        # Create connected parent and worker socket endpoints.
        parent, child = socket.socketpair()
        # Spawn a fresh interpreter and pass it the worker socket and startup
        # data, without copying the parent's live game memory through fork.
        process = multiprocessing.get_context("spawn").Process(
            target=_worker,
            args=(
                child,
                self.bot_class.__module__,
                self.bot_class.__qualname__,
                self._checkpoint,
                self.seed,
                self.timeout,
            ),
            daemon=True,  # Terminate this worker during normal parent shutdown.
        )
        self._process, self._channel = process, parent
        try:
            # Launch the worker process.
            process.start()
        finally:
            # Close the parent's copy of the worker endpoint.
            child.close()
        # Allow at least five seconds for startup, unless timeouts are disabled.
        startup_timeout = None if self.timeout is None else max(5.0, self.timeout)
        reply = _receive(parent, _deadline(startup_timeout))
        # Validate the reply and retain its checkpoint.
        self._accept(reply)

    # Validate a reply, retain its checkpoint, and return the decision if present.
    def _accept(self, reply: dict[str, Any]) -> int | None:
        # Raise if the worker reported a failure.
        if reply.get("ok") is not True:
            raise RuntimeError(str(reply.get("error", "Bot worker failed")))
        checkpoint = reply.get("checkpoint")
        value = reply.get("value")
        # Validate response types without decoding the checkpoint.
        if not isinstance(checkpoint, str) or (
            value is not None and type(value) is not int
        ):
            raise ValueError("Malformed bot response")
        # Retain the last completed checkpoint.
        self._checkpoint = checkpoint
        # Return the integer value or None; notification callers ignore it.
        return value

    # Invoke a bot callback with a bounded wait and checkpoint recovery.
    def call(self, method: str, *args: object) -> int | None:
        # Validate the callback name.
        if method not in CALLBACKS:
            raise ValueError(f"Unknown bot callback: {method}")
        self.last_error = None
        try:
            # Start a fresh worker or restore the last completed checkpoint.
            if self._channel is None:
                self._start()
            assert self._channel is not None
            # Set the overall callback deadline.
            deadline = _deadline(self.timeout)
            # Send the callback name and serialized arguments.
            _send(self._channel, {"method": method, "args": _encode(args)}, deadline)
            # Wait for a response within the remaining callback budget.
            reply = _receive(self._channel, deadline)
            # Reject a response if decoding completed after the deadline.
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Bot call exceeded its time budget")
            # Validate the reply and retain its checkpoint.
            return self._accept(reply)
        except Exception as exc:
            # Record and log failures, including timeouts.
            self.last_error = f"{method}: {type(exc).__name__}: {exc}"
            logger.warning("%s: %s", self.label, self.last_error)
            # Stop the worker while preserving the previous completed checkpoint.
            self.close()
            return None

    # Stop the worker while retaining its checkpoint.
    def close(self) -> None:
        """Stop the worker, retaining its checkpoint for future calls/games."""
        # Close the parent's socket endpoint if present.
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        # Detach the process handle before cleaning up the worker.
        process, self._process = self._process, None
        if process is not None and process.pid is not None:
            # Request termination if the worker is still running.
            if process.is_alive():
                process.terminate()
            # Wait briefly for the process to exit after the termination request.
            process.join(timeout=0.2)
            # Force termination if the worker has not exited.
            if process.is_alive():
                process.kill()
                process.join(timeout=0.2)
            # Release the process handle after the worker has exited.
            if not process.is_alive():
                process.close()

    # Return this instance when entering a with block.
    def __enter__(self) -> BotRunner:
        return self

    # Stop the worker when leaving a with block.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # Attempt worker cleanup when the runner is garbage-collected.
    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Construction may have failed, or interpreter cleanup may be underway.
            pass
