"""Collect Sentinel metrics and docker inventory per server over one SSH connection."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Callable

from .grouping import group_stacks
from .models import ContainerInfo, FleetConfig, ServerConfig, ServerSnapshot
from .parse import INSPECT_COMMAND, parse_container_metrics, parse_inspect_lines, parse_summary
from .transport import CommandResult, Runner, SSHRunner, TransportError, remote_command

SENTINEL_URL = "http://127.0.0.1:8888"
BACKOFF_STEPS = (5, 10, 20, 40, 60)
MAX_ERROR = 200


def _authed(container: str, path: str) -> str:
    # `$TOKEN` expands inside the Sentinel container. The header is built by the
    # shell builtin printf and handed to curl on stdin (`-H @-`), so the token is
    # never part of any process's argv (visible in `ps` on the host).
    inner = f'printf "Authorization: Bearer %s" "$TOKEN" | curl -fsS -H @- {SENTINEL_URL}{path}'
    return f"docker exec {container} sh -c '{inner}'"


def sentinel_commands(container: str) -> dict[str, str]:
    return {
        "health": f"docker exec {container} curl -fsS {SENTINEL_URL}/api/health",
        "version": f"docker exec {container} curl -fsS {SENTINEL_URL}/api/version",
        "summary": _authed(container, "/api/summary"),
        "containers": _authed(container, "/api/containers/current"),
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_sudo_prompt(stderr: str) -> bool:
    return "a password is required" in stderr or "sudo:" in stderr


def _join_errors(errors: list[str]) -> str | None:
    seen: list[str] = []
    for e in errors:
        if e and e not in seen:
            seen.append(e)
    if not seen:
        return None
    msg = "; ".join(seen)
    return msg if len(msg) <= MAX_ERROR else msg[: MAX_ERROR - 1] + "…"


def _parse_health(stdout: str) -> str | None:
    text = stdout.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return str(obj.get("status") or obj.get("health") or "") or None
        except json.JSONDecodeError:
            pass
    return text.strip('"')


class ServerCollector:
    def __init__(
        self,
        server: ServerConfig,
        runner_factory: Callable[[ServerConfig], Runner] = SSHRunner,
        command_timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.server = server
        self.runner_factory = runner_factory
        self.command_timeout = command_timeout
        self.clock = clock
        self._runner: Runner | None = None
        self._failures = 0
        self._retry_at = 0.0
        self._containers: list[ContainerInfo] | None = None
        self._inventory_at: datetime | None = None

    async def _run(self, cmd: str) -> CommandResult:
        assert self._runner is not None
        return await self._runner.run(remote_command(self.server, cmd), self.command_timeout)

    async def _drop_runner(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            try:
                await runner.close()
            except Exception:
                pass

    def _offline(self, error: str) -> ServerSnapshot:
        return ServerSnapshot(server=self.server, error=_join_errors([error]), fetched_at=_now())

    async def poll(self, include_inventory: bool) -> ServerSnapshot:
        now = self.clock()
        if self._failures and now < self._retry_at:
            wait = max(1, round(self._retry_at - now))
            return self._offline(f"reconnecting in {wait}s")
        try:
            return await self._poll(include_inventory)
        except TransportError as e:
            await self._drop_runner()
            self._failures += 1
            step = BACKOFF_STEPS[min(self._failures, len(BACKOFF_STEPS)) - 1]
            self._retry_at = self.clock() + step
            return self._offline(str(e) or "connection failed")
        except Exception as e:  # never raise out of poll
            await self._drop_runner()
            return self._offline(f"{type(e).__name__}: {e}")

    async def _poll(self, include_inventory: bool) -> ServerSnapshot:
        if self._runner is None:
            self._runner = self.runner_factory(self.server)
        cmds = sentinel_commands(self.server.sentinel_container)
        names = list(cmds)
        coros = [self._run(cmds[n]) for n in names]
        want_inventory = include_inventory or self._containers is None
        if want_inventory:
            names.append("inventory")
            coros.append(self._run(INSPECT_COMMAND))
        results = await asyncio.gather(*coros, return_exceptions=True)

        for r in results:
            if isinstance(r, TransportError):
                raise r

        snap = ServerSnapshot(server=self.server, fetched_at=_now())
        errors: list[str] = []
        sudo_blocked = False
        by_name = dict(zip(names, results))

        def ok_stdout(name: str) -> str | None:
            nonlocal sudo_blocked
            r = by_name[name]
            if isinstance(r, asyncio.TimeoutError):
                errors.append(f"{name}: timeout")
                return None
            if isinstance(r, BaseException):
                errors.append(f"{name}: {type(r).__name__}: {r}")
                return None
            if _is_sudo_prompt(r.stderr):
                sudo_blocked = True
                return None
            if r.exit_status != 0:
                detail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit {r.exit_status}"
                errors.append(f"{name}: {detail}")
                return None
            return r.stdout

        out = ok_stdout("health")
        if out is not None:
            snap.health = _parse_health(out)
        out = ok_stdout("version")
        if out is not None:
            snap.version = out.strip().strip('"') or None
        out = ok_stdout("summary")
        if out is not None:
            try:
                snap.host = parse_summary(json.loads(out))
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                errors.append(f"summary: bad JSON ({type(e).__name__})")
        out = ok_stdout("containers")
        if out is not None:
            try:
                snap.container_metrics = parse_container_metrics(json.loads(out))
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                errors.append(f"containers: bad JSON ({type(e).__name__})")

        if want_inventory:
            r = by_name["inventory"]
            if isinstance(r, CommandResult) and r.exit_status != 0 and r.stdout.strip() \
                    and not _is_sudo_prompt(r.stderr):
                self._containers = parse_inspect_lines(r.stdout)
                self._inventory_at = _now()
                errors.append("inventory partial")
            else:
                inv = ok_stdout("inventory")
                if inv is not None:
                    self._containers = parse_inspect_lines(inv)
                    self._inventory_at = _now()

        if sudo_blocked:
            errors = [f"sudo requires a password for {self.server.ssh_user}"]

        snap.containers = list(self._containers or [])
        snap.stacks = group_stacks(snap.containers)
        snap.inventory_at = self._inventory_at
        snap.error = _join_errors(errors)
        self._failures = 0
        return snap

    async def close(self) -> None:
        await self._drop_runner()


class FleetCollector:
    def __init__(self, cfg: FleetConfig, runner_factory: Callable[[ServerConfig], Runner] = SSHRunner):
        self.cfg = cfg
        self.collectors = [ServerCollector(s, runner_factory=runner_factory) for s in cfg.servers]

    async def poll(self, include_inventory: bool) -> list[ServerSnapshot]:
        return list(await asyncio.gather(*(c.poll(include_inventory) for c in self.collectors)))

    async def close(self) -> None:
        await asyncio.gather(*(c.close() for c in self.collectors), return_exceptions=True)
