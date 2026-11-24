"""`fleetview pull`: JSON compatible with `sentinelctl pull` (field names and meanings)."""
from __future__ import annotations

from datetime import datetime, timezone

from .models import ServerSnapshot


def _rfc3339(dt: datetime | None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _put(out: dict, key: str, value, cast=None) -> None:
    """Go `omitempty`: omit None / empty values."""
    if value is None or value == "":
        return
    out[key] = cast(value) if cast else value


def to_pull_result(s: ServerSnapshot, match: str | None) -> dict:
    out: dict = {"id": s.server.id}
    _put(out, "name", s.server.id)
    out["base_url"] = s.base_url
    out["online"] = s.online
    _put(out, "health", s.health)
    _put(out, "version", s.version)
    h = s.host
    if h is not None:
        _put(out, "cpu_percent", h.cpu_percent, float)
        _put(out, "memory_used_percent", h.mem_percent, float)
        _put(out, "memory_total_bytes", h.mem_total, int)
        _put(out, "memory_used_bytes", h.mem_used, int)
        _put(out, "disk_used_percent", h.disk_root_percent, float)

    needle = (match or "").lower()
    total = running = healthy = bad = matched = 0
    for c in s.containers:
        if needle and not (needle in c.name.lower() or needle in c.id.lower() or needle in c.image.lower()):
            continue
        matched += 1
        total += 1
        health = (c.health or "unknown").lower()
        if c.state.lower() == "running":
            running += 1
            if health == "healthy":
                healthy += 1
            elif health not in ("unknown", ""):
                bad += 1
    out.update(container_total=total, container_running=running, container_healthy=healthy,
               container_unhealthy=bad, matched_filter=matched)
    _put(out, "error", s.error)
    out["fetched_at"] = _rfc3339(s.fetched_at)
    return out


def pull_output(snaps: list[ServerSnapshot], match: str | None) -> dict:
    return {"timestamp": _rfc3339(None), "results": [to_pull_result(s, match) for s in snaps]}


def passes_ci_gates(results: list[dict], filter_applied: bool) -> bool:
    for r in results:
        if not r.get("online"):
            return False
        if filter_applied and r.get("matched_filter", 0) == 0:
            return False
        if r.get("container_unhealthy", 0) > 0:
            return False
    return True
