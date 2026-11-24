"""Group containers into stacks using Coolify / Docker Compose labels."""
from __future__ import annotations

import re

from .models import ContainerInfo, Stack
from .parse import display_name  # re-exported: the TUI imports grouping.display_name

__all__ = [
    "PLATFORM_NAMES", "is_platform", "stack_key", "stack_kind", "parse_domains",
    "group_stacks", "display_name",
]

PLATFORM_NAMES: frozenset[str] = frozenset({
    "coolify", "coolify-db", "coolify-redis", "coolify-realtime", "coolify-sentinel",
    "coolify-log-drain", "coolify-cadvisor", "coolify-grafana", "coolify-node-exporter",
    "coolify-prometheus", "fleet-sentinel", "sentinel", "promtail",
})

_DB_PROXY = re.compile(r"^([a-z0-9]{24})-proxy$")
_CADDY_KEY = re.compile(r"^caddy_\d+$")
_TRAEFIK_RULE_KEY = re.compile(r"^traefik\.http\.routers\.[^.]+\.rule$")
_CADDY_HOST = re.compile(r"https?://([^\s,/]+)")
_TRAEFIK_HOST = re.compile(r"Host\(`([^`]+)`\)")
COMPOSE_PROJECT = "com.docker.compose.project"
_COOLIFY_TYPES = {"application", "service", "database"}


def is_platform(c: ContainerInfo) -> bool:
    return c.name in PLATFORM_NAMES or c.name.startswith("coolify-proxy")


def _is_db_proxy(c: ContainerInfo) -> bool:
    return _DB_PROXY.match(c.name) is not None


def stack_key(c: ContainerInfo) -> str:
    m = _DB_PROXY.match(c.name)
    if m:
        return m.group(1)
    return c.labels.get(COMPOSE_PROJECT) or c.name


def stack_kind(c: ContainerInfo) -> str:
    t = c.labels.get("coolify.type")
    if t in _COOLIFY_TYPES:
        return "coolify-" + t
    if c.labels.get(COMPOSE_PROJECT):
        return "compose"
    return "standalone"


def parse_domains(labels: dict[str, str]) -> list[str]:
    hosts: set[str] = set()
    for k, v in labels.items():
        if not isinstance(v, str):
            continue
        if _CADDY_KEY.match(k):
            hosts.update(_CADDY_HOST.findall(v))
        elif _TRAEFIK_RULE_KEY.match(k):
            hosts.update(_TRAEFIK_HOST.findall(v))
    return sorted(hosts)


def group_stacks(containers: list[ContainerInfo]) -> list[Stack]:
    members: dict[str, list[ContainerInfo]] = {}
    for c in containers:
        members.setdefault(stack_key(c), []).append(c)

    stacks: list[Stack] = []
    for key, cs in members.items():
        lead = next((c for c in cs if not _is_db_proxy(c)), cs[0])
        lab = lead.labels
        kind = stack_kind(lead)
        domains: set[str] = set()
        for c in cs:
            domains.update(parse_domains(c.labels))
        stacks.append(Stack(
            key=key,
            kind=kind,
            platform=all(is_platform(c) for c in cs),
            project=lab.get("coolify.projectName") or None,
            environment=lab.get("coolify.environmentName") or None,
            resource=lab.get("coolify.resourceName") or lab.get("coolify.serviceName") or None,
            coolify_uuid=key if kind.startswith("coolify-") else None,
            domains=sorted(domains),
            working_dir=lab.get("com.docker.compose.project.working_dir") or None,
            containers=cs,
        ))
    stacks.sort(key=lambda s: (s.platform, s.project or "", s.resource or s.key))
    return stacks
