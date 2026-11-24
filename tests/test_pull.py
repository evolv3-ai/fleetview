import asyncio
import json
import re

from fleetview.collector import ServerCollector
from fleetview.models import ContainerInfo, HostMetrics, ServerSnapshot
from fleetview.pull import passes_ci_gates, pull_output, to_pull_result

from .conftest import load_json
from .fakes import FakeRunner, fixture_responses, server


def _snap(summary="summary_full.json", containers="containers_current_full.json"):
    fake = FakeRunner(fixture_responses(summary=summary, containers=containers))
    return asyncio.run(ServerCollector(server(), runner_factory=lambda s: fake).poll(True))


def _c(name, state, health, image="img"):
    return ContainerInfo(id="id-" + name, name=name, image=image, state=state, health=health,
                         restart_count=0, labels={}, started_at=None)


def _online_snap(containers):
    host = HostMetrics(cpu_percent=1.0, mem_total=100, mem_used=50, mem_percent=50.0, disk_total=1,
                       disk_used=1, disk_root_percent=10.0, load1=None, load5=None, load15=None)
    return ServerSnapshot(server=server(), health="ok", version="1.1.5", host=host, containers=containers)


def test_pull_field_names_match_sentinelctl():
    golden = load_json("sentinelctl_pull.json")
    union = set()
    for r in golden["results"]:
        union |= set(r)
    s = _snap()
    s.error = "something"  # make the optional error field present too
    result = to_pull_result(s, None)
    assert set(result) >= union
    assert result["name"] == result["id"] == "htz-04-5-213"
    assert result["base_url"] == "ssh://root@5.161.113.213/coolify-sentinel"
    assert result["disk_used_percent"] == 32.8
    assert result["memory_total_bytes"] == 8589934592 and isinstance(result["memory_total_bytes"], int)
    assert result["memory_used_bytes"] == 3865470566
    assert result["memory_used_percent"] == 45.0
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", result["fetched_at"])
    # types match the golden output
    g0 = golden["results"][0]
    for k in union:
        assert type(result[k]) is type(g0[k]) or {type(result[k]), type(g0[k])} <= {int, float}, k


def test_counts_match_sentinelctl_rules():
    cs = [_c("a", "running", "healthy"), _c("b", "running", None), _c("c", "running", "unhealthy"),
          _c("d", "running", "starting"), _c("e", "exited", None), _c("f", "restarting", None)]
    r = to_pull_result(_online_snap(cs), None)
    assert (r["container_total"], r["container_running"], r["container_healthy"],
            r["container_unhealthy"], r["matched_filter"]) == (6, 4, 1, 2, 6)


def test_unhealthy_only_counted_when_running():
    r = to_pull_result(_online_snap([_c("a", "exited", "unhealthy")]), None)
    assert r["container_unhealthy"] == 0 and r["container_total"] == 1


def test_match_filter_counts_only_matched():
    cs = [_c("OpenBrain-api", "running", "healthy"), _c("x", "running", "unhealthy", image="ghcr.io/openbrain/db"),
          _c("other", "running", "unhealthy")]
    r = to_pull_result(_online_snap(cs), "openbrain")
    assert (r["matched_filter"], r["container_total"], r["container_unhealthy"]) == (2, 2, 1)
    r = to_pull_result(_online_snap(cs), "id-oth")
    assert r["matched_filter"] == 1


def test_pull_metrics_off_is_offline_but_counts_containers():
    s = _snap(summary="summary_metrics_off.json", containers="containers_current_metrics_off.json")
    r = to_pull_result(s, None)
    assert r["online"] is False
    assert "cpu_percent" not in r
    assert "memory_used_percent" not in r and "memory_total_bytes" not in r
    assert isinstance(r["disk_used_percent"], float)
    assert r["container_total"] > 0
    assert r["health"] == "ok" and r["version"] == "1.1.5"
    assert "error" not in r


def test_pull_output_shape():
    out = pull_output([_snap()], None)
    assert set(out) == {"timestamp", "results"}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", out["timestamp"])
    json.dumps(out)


def test_ci_gates():
    good = {"online": True, "matched_filter": 3, "container_unhealthy": 0}
    assert passes_ci_gates([good, dict(good)], False) is True
    assert passes_ci_gates([good, dict(good, online=False)], False) is False
    assert passes_ci_gates([dict(good, container_unhealthy=1)], False) is False
    assert passes_ci_gates([dict(good, matched_filter=0)], True) is False
    assert passes_ci_gates([dict(good, matched_filter=0)], False) is True
