"""Test doubles for the SSH transport."""
from __future__ import annotations

from fleetview.models import ServerConfig
from fleetview.transport import CommandResult

from .conftest import fixture_path


def ok(stdout: str) -> CommandResult:
    return CommandResult(0, stdout, "")


def fixture_responses(summary="summary_full.json", containers="containers_current_full.json",
                      inspect="inspect_htz04.jsonl") -> dict:
    return {
        "/api/health": ok("ok"),
        "/api/version": ok("1.1.5\n"),
        "/api/summary": ok(fixture_path(summary).read_text(encoding="utf-8")),
        "/api/containers/current": ok(fixture_path(containers).read_text(encoding="utf-8")),
        "docker ps": ok(fixture_path(inspect).read_text(encoding="utf-8")),
    }


class FakeRunner:
    def __init__(self, responses: dict):
        self.responses = responses
        self.commands: list[str] = []
        self.closed = False

    async def run(self, cmd: str, timeout: float):
        self.commands.append(cmd)
        for needle, resp in self.responses.items():
            if needle in cmd:
                if isinstance(resp, BaseException):
                    raise resp
                return resp
        return CommandResult(127, "", f"no fake for {cmd}")

    async def close(self):
        self.closed = True


def server(id="htz-04-5-213", user="root", ip="5.161.113.213") -> ServerConfig:
    return ServerConfig(id=id, ip=ip, ssh_user=user, ssh_key="~/.ssh/k",
                        sentinel_mode="coolify", sentinel_container="coolify-sentinel")
