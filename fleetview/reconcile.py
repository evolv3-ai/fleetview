"""Compare the fleet snapshot with the profile's deployments{} and servers[].apps. Report only."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_VERSION_SUFFIX = re.compile(r"-\d.*$")
# Platform software, not a deployed app: never drift. Matched after the version suffix is stripped.
_PLATFORM_APPS = frozenset({"coolify", "docker", "sentinel", "cloudflared"})


@dataclass
class ReconcileReport:
    untracked: list[tuple[str, str, str | None]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    not_running: list[tuple[str, str]] = field(default_factory=list)
    apps_drift: list[tuple[str, str]] = field(default_factory=list)


def _dep_servers(dep: dict) -> list[str]:
    ids = dep.get("serverIds")
    if isinstance(ids, list):
        return [str(i) for i in ids]
    one = dep.get("serverId")
    return [str(one)] if one else []


def _dep_key(dep: dict) -> str | None:
    return dep.get("stackKey") or dep.get("coolifyAppUuid") or None


def reconcile(snapshot: dict, profile: dict) -> ReconcileReport:
    report = ReconcileReport()
    servers: dict = snapshot.get("servers") or {}
    deployments: dict = profile.get("deployments") or {}

    tracked: set[tuple[str, str]] = set()
    for name, dep in deployments.items():
        if not isinstance(dep, dict):
            continue
        key = _dep_key(dep)
        if not key:
            continue
        observed = [sid for sid in _dep_servers(dep) if sid in servers]
        for sid in _dep_servers(dep):
            tracked.add((sid, key))
        if not observed:
            continue  # server not in snapshot: cannot judge
        stacks = [servers[sid]["stacks"][key] for sid in observed if key in servers[sid].get("stacks", {})]
        if not stacks:
            report.missing.append((name, key))
        elif not any(c.get("state") == "running" for st in stacks for c in st.get("containers", [])):
            report.not_running.append((name, key))

    for sid, srv in servers.items():
        for key, st in (srv.get("stacks") or {}).items():
            if st.get("platform"):
                continue
            if (sid, key) not in tracked:
                report.untracked.append((sid, key, st.get("resource")))

    for prof_srv in profile.get("servers") or []:
        if not isinstance(prof_srv, dict):
            continue
        sid = prof_srv.get("id")
        if sid not in servers:
            continue
        haystack: list[str] = []
        for key, st in (servers[sid].get("stacks") or {}).items():
            if st.get("platform"):
                continue
            haystack += [key, st.get("resource") or "", st.get("project") or ""]
            haystack += [c.get("image") or "" for c in st.get("containers", [])]
        haystack = [h.lower() for h in haystack if h]
        for app in prof_srv.get("apps") or []:
            needle = _VERSION_SUFFIX.sub("", str(app).lower()).strip()
            if needle in _PLATFORM_APPS:
                continue
            if not needle or not any(needle in h for h in haystack):
                report.apps_drift.append((sid, str(app)))
    return report


def _section(title: str, rows: list[tuple]) -> list[str]:
    lines = [f"{title} ({len(rows)})"]
    if not rows:
        lines.append("  none")
    for r in rows:
        lines.append("  " + "  ".join("-" if v is None else str(v) for v in r))
    return lines


def format_report(r: ReconcileReport) -> str:
    out: list[str] = []
    out += _section("Untracked stacks", r.untracked)
    out += [""] + _section("Missing deployments", r.missing)
    out += [""] + _section("Not running", r.not_running)
    out += [""] + _section("Apps drift", r.apps_drift)
    return "\n".join(out) + "\n"
