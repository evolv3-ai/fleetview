"""Observed-state fleet container snapshot (spec §3), written for the .admin profile tooling."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import ServerSnapshot

DEFAULT_PATH = Path("~/.admin/generated/fleet-containers.json")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_snapshot(snaps: list[ServerSnapshot], generated_at: datetime) -> dict:
    servers: dict = {}
    for s in snaps:
        if s.inventory_at is None:
            continue  # no inventory: absent rather than "zero stacks"
        stacks = {}
        for st in s.stacks:
            stacks[st.key] = {
                "kind": st.kind,
                "project": st.project,
                "environment": st.environment,
                "resource": st.resource,
                "coolifyUuid": st.coolify_uuid,
                "domains": list(st.domains),
                "workingDir": st.working_dir,
                "platform": st.platform,
                "containers": [
                    {"name": c.name, "image": c.image, "state": c.state,
                     "health": c.health, "restartCount": c.restart_count}
                    for c in st.containers
                ],
            }
        servers[s.server.id] = {
            "fetchedAt": _iso(s.inventory_at),
            "sentinel": {"mode": s.server.sentinel_mode, "version": s.version},
            "stacks": stacks,
        }
    return {"generatedAt": _iso(generated_at), "servers": servers}


def write_snapshot(path: Path, data: dict) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
