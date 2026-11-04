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

# Creates a logger for bot_runner.py
logger = logging.getLogger(__name__)
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
CALLBACKS = frozenset(
    {"on_game_start", "get_bid", "choose_hidden_gem", "on_round_end", "on_game_end"}
)


# Based on the timeout, returns time as float by which the bot must complete
def _deadline(timeout: float | None) -> float | None:
    return None if timeout is None else time.monotonic() + timeout


# Sets a timeout on the bot's channel if applicable
def _set_timeout(channel: socket.socket, deadline: float | None) -> None:
    if deadline is None:
        channel.settimeout(None)
    else:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Bot call exceeded its time budget")
        channel.settimeout(remaining)


# Sends message to a bot worker and enforces a timeout as necessary
def _send(
    channel: socket.socket, message: dict[str, Any], deadline: float | None
) -> None:
    payload = json.dumps(message).encode()
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Bot message or checkpoint exceeds the 16 MiB limit")
    _set_timeout(channel, deadline)
    # Continues sending data until all data is sent or error occurs
    channel.sendall(struct.pack("!I", len(payload)) + payload)


# Wait for a message from the bot of defined size, with a timeout
def _read_exact(channel: socket.socket, size: int, deadline: float | None) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        _set_timeout(channel, deadline)
        chunk = channel.recv(min(size - len(chunks), 65536))
        if not chunk:
            raise EOFError("Bot worker disconnected")
        chunks.extend(chunk)
    return bytes(chunks)


# Reads data from the bot, first getting the size as a 4-byte integer, then getting the rest of the json data
def _receive(channel: socket.socket, deadline: float | None) -> dict[str, Any]:
    # Gets the size of the message as the first four bytes
    size = struct.unpack("!I", _read_exact(channel, 4, deadline))[0]
    if size > MAX_MESSAGE_BYTES:
        raise ValueError("Bot message or checkpoint exceeds the 16 MiB limit")
    # Waits for the rest of the message
    message = json.loads(_read_exact(channel, size, deadline))
    if not isinstance(message, dict):
        raise ValueError("Expected a bot message object")
    return message


# Base64 encodes a pickled python object
def _encode(value: object) -> str:
    return base64.b64encode(pickle.dumps(value)).decode("ascii")


# Base64 decodes a pickled python object and returns it as an object
def _decode(value: str) -> Any:
    # Called only inside workers, never on bot-produced data in the game process.
    return pickle.loads(base64.b64decode(value))


# Encodes the bot's pickled state and the current internal state of the pseudo-random number generator
def _checkpoint(bot: Bot) -> str:
    return _encode((bot.save_state(), random.getstate()))


#
def _worker(
    channel: socket.socket, # Channel of communication with the main process (harness)
    module: str, # Module that the worker bot is from
    qualname: str, # The dotted path of the bot class
    checkpoint: str | None, # Saved checkpoint of the bot, if it exists
    seed: int | None, # Random seed of the worker
    timeout: float | None, # Timeout in seconds 
) -> None:
    try:
        # multiprocessing inherits argv; bot callbacks do not need host CLI seeds.
        sys.argv = ["megagem-bot"]
        # Imports the python module that the worker bot is from
        bot_class: Any = importlib.import_module(module)
        # Get the class form the dotted path (qualname) and module
        for part in qualname.split("."):
            bot_class = getattr(bot_class, part)
        # Make sure that the bot class inherits from Bot
        if not isinstance(bot_class, type) or not issubclass(bot_class, Bot):
            raise TypeError("Bot class must inherit from Bot")
        # Sets the random seed of the worker
        random.seed(seed)
        if checkpoint is None:
            # Instantiate a fresh bot if there is no checkpoint
            bot = bot_class()
        else:
            # Otherwise, decode the checkpoint and load it into the bot object/random module
            bot = bot_class.__new__(bot_class) # Foregoes calling __init__()
            state, rng_state = _decode(checkpoint)
            bot.load_state(state)
            random.setstate(rng_state)
        # Sets the timeout of the bot
        bot.timeout_seconds = timeout
        # Notifies the caller that the worker has been created correctly and sends its checkpoint
        _send(channel, {"ok": True, "checkpoint": _checkpoint(bot)}, None)
        while True:
            # Wait for a request on the channel
            request = _receive(channel, None)
            method = request["method"]
            # Check if a known method is requested form the bot
            if method not in CALLBACKS:
                raise ValueError("Unknown bot callback")
            try:
                args = _decode(request["args"])
                # Calls the defined method with defined arguments on the bot
                result = getattr(bot, method)(*args)
                # Never serialize arbitrary return objects in the parent process.
                # Bot methods should only ever return an int or None
                value = result if type(result) is int else None
                # Send the result and bot checkpoint. Checkpoint will never be unpickled in the parent process
                _send(
                    channel,
                    {"ok": True, "value": value, "checkpoint": _checkpoint(bot)},
                    None,
                )
            except Exception as exc:
                # Handle and forward error
                _send(
                    channel,
                    {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                    None,
                )
    except (EOFError, OSError):
        pass
    except Exception as exc:
        # Handle and forward error
        try:
            _send(channel, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, None)
        except (OSError, ValueError):
            pass
    finally:
        # Close the socket with the parent
        channel.close()


# Wrapper around a bot that is able to start it as a child process
# and communicate functions to it/receive return values
class BotRunner:
    """Own one bot's worker and memory; can be reused across multiple games.

    Callback time includes argument transport and checkpointing. Worker startup
    has a separate allowance of at least five seconds, or no limit with None.
    """

    def __init__(
        self,
        bot_class: type[Bot] = Bot, # Expects a Bot class/subclass, not object
        *,
        timeout: float | None = 1.0,
        seed: int | None = None,
    ) -> None:
        # Checks on received arguments
        if not issubclass(bot_class, Bot):
            raise TypeError("Bot class must inherit from Bot")
        if "<locals>" in bot_class.__qualname__ or bot_class.__module__ == "__main__":
            raise ValueError("Define bot classes in an importable module")
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Bot timeout must be positive and finite, or None")
        self.bot_class = bot_class
        self.timeout = timeout
        self.seed = seed
        # Temporary label for the bot, to be updated with player number from the Player class 
        self.label = bot_class.__name__
        self.last_error: str | None = None
        self._checkpoint: str | None = None
        self._process: BaseProcess | None = None
        self._channel: socket.socket | None = None

    # Starts the bot running in a child process with a socket between them
    def _start(self) -> None:
        # Creates a scoket pair that can send/receive data from each other
        parent, child = socket.socketpair()
        # Creates the worker function in a separate process object, inheriting the child end of the
        # socket, as well as the necessary information to run the bot
        # Uses "spawn" to make sure to start a fresh Python interpreter. Does NOT fork
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
            daemon=True, # Daemon process, automatically terminates when the parent process exits
        )
        self._process, self._channel = process, parent
        try:
            # Starts the child process, actually creating it
            process.start()
        finally:
            # Closes the socket
            child.close()
        # Waits for the startup "ok" from the child, with timeout at most 5 seconds
        startup_timeout = None if self.timeout is None else max(5.0, self.timeout)
        reply = _receive(parent, _deadline(startup_timeout))
        # Process reply
        self._accept(reply)

    # Method to process replies of the bot, saving the checkpoint and possibly forwarding a return value
    def _accept(self, reply: dict[str, Any]) -> int | None:
        # Indicate if the bot worker has failed
        if reply.get("ok") is not True:
            raise RuntimeError(str(reply.get("error", "Bot worker failed")))
        checkpoint = reply.get("checkpoint")
        value = reply.get("value")
        # Ensure that the value and checkpoint are valid
        if not isinstance(checkpoint, str) or (
            value is not None and type(value) is not int
        ):
            raise ValueError("Malformed bot response")
        # Save the checkpoint
        self._checkpoint = checkpoint
        # Forward the return value (or None)
        return value

    # Calls a method on the bot worker with provided arguments
    def call(self, method: str, *args: object) -> int | None:
        # Validates the method name
        if method not in CALLBACKS:
            raise ValueError(f"Unknown bot callback: {method}")
        self.last_error = None
        try:
            # Starts if the bot worker process has not already been started
            if self._channel is None:
                self._start()
            assert self._channel is not None
            # Gets the timeout deadline
            deadline = _deadline(self.timeout)
            # Sends a method to the bot worker
            _send(self._channel, {"method": method, "args": _encode(args)}, deadline)
            # Receive a response from the bot, with a timeout
            reply = _receive(self._channel, deadline)
            # Raise if there was a timeout
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("Bot call exceeded its time budget")
            # Process reply
            return self._accept(reply)
        except Exception as exc:
            # Log errors, including timeout
            self.last_error = f"{method}: {type(exc).__name__}: {exc}"
            logger.warning("%s: %s", self.label, self.last_error)
            # Stop the worker bot
            self.close()
            return None

    # Stops the worker, while retaining its checkpoint
    def close(self) -> None:
        """Stop the worker, retaining its checkpoint for future calls/games."""
        # Close the socket channel as necessary
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        # Temporariliy save and reset self._process
        process, self._process = self._process, None
        if process is not None and process.pid is not None:
            # Terminate the process as necessary
            if process.is_alive():
                process.terminate()
            # Give time for a graceful termination
            process.join(timeout=0.2)
            # Kill the process as necessary if still alive
            if process.is_alive():
                process.kill()
                process.join(timeout=0.2)
            # Release Process object resources
            if not process.is_alive():
                process.close()

    # Executes when entering a "with" block
    def __enter__(self) -> BotRunner:
        return self

    # Executes when leaving a "with" block, makes sure to cleanup the child process
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # Executes when the object is about to be destroyed, makes sure to cleanup the child process
    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Construction may have failed, or interpreter cleanup may be underway.
            pass
