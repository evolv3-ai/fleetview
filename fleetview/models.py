"""Data model: servers, containers, metrics, stacks, per-poll snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

Number = float | int | None


def _default_thresholds() -> dict[str, int]:
    return {
        "cpu_warn": 70, "cpu_crit": 90,
        "mem_warn": 70, "mem_crit": 90,
        "disk_warn": 70, "disk_crit": 90,
    }


@dataclass
class ServerConfig:
    id: str
    ip: str
    ssh_user: str
    ssh_key: str
    sentinel_mode: str
    sentinel_container: str
    provider: str = ""
    role: str = ""
    specs: str = ""
    domain: str = ""
    url: str = ""


@dataclass
class FleetConfig:
    servers: list[ServerConfig]
    refresh_interval: int = 5
    inventory_interval: int = 60
    thresholds: dict[str, int] = field(default_factory=_default_thresholds)


@dataclass(frozen=True)
class ContainerInfo:
    id: str
    name: str
    image: str
    state: str
    health: str | None
    restart_count: int
    labels: dict[str, str]
    started_at: str | None


@dataclass
class ContainerMetrics:
    cpu_percent: float | None
    mem_used: int | None
    mem_percent: float | None


@dataclass
class HostMetrics:
    cpu_percent: Number
    mem_total: Number
    mem_used: Number
    mem_percent: Number
    disk_total: Number
    disk_used: Number
    disk_root_percent: Number
    load1: Number
    load5: Number
    load15: Number


@dataclass
class Stack:
    key: str
    kind: str
    platform: bool
    project: str | None
    environment: str | None
    resource: str | None
    coolify_uuid: str | None
    domains: list[str]
    working_dir: str | None
    containers: list[ContainerInfo]


@dataclass
class ServerSnapshot:
    server: ServerConfig
    health: str | None = None
    version: str | None = None
    host: HostMetrics | None = None
    containers: list[ContainerInfo] = field(default_factory=list)
    container_metrics: dict[str, ContainerMetrics] = field(default_factory=dict)
    stacks: list[Stack] = field(default_factory=list)
    error: str | None = None
    fetched_at: datetime | None = None
    inventory_at: datetime | None = None

    @property
    def online(self) -> bool:
        h = self.host
        return (
            self.health == "ok"
            and h is not None
            and h.cpu_percent is not None
            and h.mem_percent is not None
            and h.disk_root_percent is not None
        )

    @property
    def base_url(self) -> str:
        s = self.server
        return f"ssh://{s.ssh_user}@{s.ip}/{s.sentinel_container}"
