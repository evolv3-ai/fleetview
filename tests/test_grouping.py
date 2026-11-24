import json

from fleetview.grouping import group_stacks, is_platform, parse_domains, stack_key, stack_kind
from fleetview.models import ContainerInfo

from .conftest import fixture_path


def _read_jsonl(name):
    out = []
    for line in fixture_path(name).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        out.append(ContainerInfo(
            id=o["id"], name=o["name"].lstrip("/"), image=o["image"], state=o["state"],
            health=o["health"], restart_count=o["restartCount"], labels=o["labels"] or {},
            started_at=o["startedAt"],
        ))
    return out


def _c(name, labels=None, state="running"):
    return ContainerInfo(id=name, name=name, image="img", state=state, health=None,
                         restart_count=0, labels=labels or {}, started_at=None)


def test_coolify_service_groups_by_resource_uuid():
    stacks = group_stacks(_read_jsonl("inspect_htz03.jsonl"))
    lf = [s for s in stacks if any(c.name.startswith("langfuse-") for c in s.containers)]
    assert len(lf) == 1
    s = lf[0]
    names = {c.name.split("-e14got")[0] for c in s.containers}
    assert names == {"langfuse", "langfuse-worker", "clickhouse", "redis", "postgres"}
    assert s.kind == "coolify-service"
    assert s.project == "base"
    assert s.coolify_uuid == s.key == "e14got5549ldxlaqmz23d7fi"
    assert "langfuse.self-host.ai" in s.domains


def test_group_proxy_joins_resource_stack():
    uuid = "skko8sg00c8sgc0wgw8k4s08"
    proxy = _c(f"{uuid}-proxy", {"com.docker.compose.project": "proxy"})
    db = _c(uuid, {"com.docker.compose.project": uuid, "coolify.type": "database",
                   "coolify.projectName": "base", "coolify.resourceName": "pg"})
    assert stack_key(proxy) == uuid
    stacks = group_stacks([proxy, db])
    assert len(stacks) == 1
    s = stacks[0]
    assert s.key == uuid
    assert s.kind == "coolify-database"
    assert s.resource == "pg"
    assert s.project == "base"


def test_proxy_first_does_not_supply_stack_fields():
    uuid = "skko8sg00c8sgc0wgw8k4s08"
    proxy = _c(f"{uuid}-proxy", {"com.docker.compose.project": "proxy"})
    db = _c(uuid, {"com.docker.compose.project": uuid, "coolify.type": "database"})
    assert group_stacks([proxy, db])[0].kind == "coolify-database"


def test_domains_from_multi_host_traefik_rule():
    labels = {"traefik.http.routers.x.rule":
              "Host(`a.example.com`) || Host(`b.example.com`) && PathPrefix(`/`)"}
    assert parse_domains(labels) == ["a.example.com", "b.example.com"]
    assert parse_domains({"caddy_0": "https://x.example.com, https://www.x.example.com"}) == [
        "www.x.example.com", "x.example.com"]


def test_domains_ignore_non_rule_labels():
    labels = {"traefik.http.routers.x.middlewares": "Host(`nope.example.com`)",
              "caddy_0.handle_path": "https://also-nope.example.com",
              "caddy_1": "http://y.example.com:8080/path"}
    assert parse_domains(labels) == ["y.example.com:8080"]


def test_unlabeled_container_is_standalone():
    c = _c("jfin-stream-auth")
    assert stack_key(c) == "jfin-stream-auth"
    assert stack_kind(c) == "standalone"
    s = group_stacks([c])[0]
    assert s.key == "jfin-stream-auth"
    assert s.kind == "standalone"
    assert s.platform is False
    assert s.coolify_uuid is None


def test_compose_kind_and_working_dir():
    c = _c("fleet-monitoring-grafana-1", {"com.docker.compose.project": "fleet-monitoring",
                                          "com.docker.compose.project.working_dir": "/opt/fm"})
    s = group_stacks([c])[0]
    assert (s.kind, s.working_dir, s.coolify_uuid) == ("compose", "/opt/fm", None)


def test_platform_stacks_sort_last():
    stacks = group_stacks(_read_jsonl("inspect_htz04.jsonl"))
    flags = [s.platform for s in stacks]
    first_platform = flags.index(True)
    assert all(flags[first_platform:])
    assert not any(flags[:first_platform])
    assert first_platform == 7
    proxy = next(s for s in stacks if s.key == "coolify-proxy")
    assert proxy.platform is True
    assert is_platform(_c("coolify-proxy-error-pages"))
    assert not is_platform(_c("coolify-something-else"))
