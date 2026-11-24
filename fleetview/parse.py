"""Parsers for Rust Sentinel JSON and `docker inspect` output."""
from __future__ import annotations

import json
from typing import Any

from .models import ContainerInfo, ContainerMetrics, HostMetrics

# One JSON object per container per line. `index .State "Health"` instead of
# `.State.Health`: Docker 29 errors on a missing map key inside `if`.
INSPECT_FORMAT: str = (
    '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Config.Image}},'
    '"state":{{json .State.Status}},'
    '"health":{{with index .State "Health"}}{{json .Status}}{{else}}null{{end}},'
    '"restartCount":{{.RestartCount}},"labels":{{json .Config.Labels}},'
    '"startedAt":{{json .State.StartedAt}}}'
)

INSPECT_COMMAND: str = (
    "docker ps -aq --no-trunc | xargs -r docker inspect --format '" + INSPECT_FORMAT + "'"
)


def parse_inspect_lines(text: str) -> list[ContainerInfo]:
    out: list[ContainerInfo] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(o, dict):
            continue
        labels = o.get("labels") or {}
        out.append(ContainerInfo(
            id=str(o.get("id") or ""),
            name=str(o.get("name") or "").lstrip("/"),
            image=str(o.get("image") or ""),
            state=str(o.get("state") or ""),
            health=o.get("health"),
            restart_count=int(o.get("restartCount") or 0),
            labels={str(k): str(v) for k, v in labels.items()},
            started_at=o.get("startedAt"),
        ))
    return out


def _num(d: Any, key: str):
    if not isinstance(d, dict):
        return None
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v) if isinstance(v, str) else v
    except ValueError:
        return None


def parse_summary(obj: dict) -> HostMetrics:
    cpu = obj.get("cpu")
    mem = obj.get("memory")
    load = obj.get("load")
    root = None
    for d in obj.get("disk") or []:
        if isinstance(d, dict) and d.get("mount") == "/":
            root = d
            break
    return HostMetrics(
        cpu_percent=_num(cpu, "percent"),
        mem_total=_num(mem, "total"),
        mem_used=_num(mem, "used"),
        mem_percent=_num(mem, "usedPercent"),
        disk_total=_num(root, "total"),
        disk_used=_num(root, "used"),
        disk_root_percent=_num(root, "usedPercent"),
        load1=_num(load, "load1"),
        load5=_num(load, "load5"),
        load15=_num(load, "load15"),
    )


def display_name(c: ContainerInfo) -> str:
    return c.labels.get("coolify.name") or c.name


def parse_container_metrics(arr: list[dict]) -> dict[str, ContainerMetrics]:
    out: dict[str, ContainerMetrics] = {}
    for item in arr or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        cpu = _num(item.get("cpu"), "percent")
        mem = item.get("memory")
        used = _num(mem, "used")
        out[str(item["id"])] = ContainerMetrics(
            cpu_percent=float(cpu) if cpu is not None else None,
            mem_used=int(used) if used is not None else None,
            mem_percent=_num(mem, "usedPercent"),
        )
    return out
