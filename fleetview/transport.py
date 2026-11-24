"""SSH transport: one persistent asyncssh connection per server."""
from __future__ import annotations

import asyncio
import os
import shlex
from typing import NamedTuple, Protocol

import asyncssh

from .models import ServerConfig


class CommandResult(NamedTuple):
    exit_status: int
    stdout: str
    stderr: str


class TransportError(Exception):
    """The SSH connection could not be made or was lost."""


class Runner(Protocol):
    async def run(self, cmd: str, timeout: float) -> CommandResult: ...

    async def close(self) -> None: ...


def remote_command(server: ServerConfig, cmd: str) -> str:
    """Wrap a command for the server's SSH user (non-root users get passwordless sudo)."""
    if server.ssh_user != "root":
        return "sudo -n sh -c " + shlex.quote(cmd)
    return cmd


def _known_hosts() -> str | None:
    path = os.path.expanduser("~/.ssh/known_hosts")
    return path if os.path.exists(path) else None


class SSHRunner:
    """Runs commands over a lazily opened, reused SSH connection."""

    def __init__(self, server: ServerConfig, connect_timeout: float = 10.0):
        self.server = server
        self.connect_timeout = connect_timeout
        self._conn: asyncssh.SSHClientConnection | None = None
        self._lock = asyncio.Lock()

    async def _connection(self) -> asyncssh.SSHClientConnection:
        async with self._lock:
            if self._conn is None:
                known = _known_hosts()
                if known is None:
                    raise TransportError("no ~/.ssh/known_hosts; refusing unverified host key")
                try:
                    self._conn = await asyncio.wait_for(
                        asyncssh.connect(
                            host=self.server.ip,
                            username=self.server.ssh_user,
                            client_keys=[os.path.expanduser(self.server.ssh_key)],
                            known_hosts=known,
                            agent_path=None,
                            keepalive_interval=30,
                        ),
                        timeout=self.connect_timeout,
                    )
                except asyncio.TimeoutError as e:
                    raise TransportError(f"connect timeout after {self.connect_timeout:g}s") from e
                except (OSError, asyncssh.Error) as e:
                    raise TransportError(_short(e)) from e
            return self._conn

    async def run(self, cmd: str, timeout: float) -> CommandResult:
        conn = await self._connection()
        try:
            res = await asyncio.wait_for(conn.run(cmd, check=False), timeout=timeout)
        except asyncio.TimeoutError:
            raise
        except (OSError, asyncssh.Error) as e:
            await self._reset()
            raise TransportError(_short(e)) from e
        status = res.exit_status if res.exit_status is not None else -1
        return CommandResult(status, _text(res.stdout), _text(res.stderr))

    async def _reset(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()

    async def close(self) -> None:
        await self._reset()


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def _short(e: BaseException) -> str:
    msg = str(e).strip() or type(e).__name__
    return msg.splitlines()[0]
