from fleetview.models import ContainerInfo
from fleetview.parse import (
    INSPECT_COMMAND, INSPECT_FORMAT, display_name, parse_container_metrics,
    parse_inspect_lines, parse_summary,
)

from .conftest import fixture_path, load_json


def test_parse_inspect_fixture():
    text = fixture_path("inspect_htz04.jsonl").read_text(encoding="utf-8")
    cs = parse_inspect_lines(text)
    assert len(cs) == len([l for l in text.splitlines() if l.strip()])
    proxy = [c for c in cs if c.name == "coolify-proxy"]
    assert len(proxy) == 1 and proxy[0].health == "healthy"
    assert all(not c.name.startswith("/") for c in cs)
    assert all(isinstance(c.labels, dict) for c in cs)


def test_parse_inspect_skips_garbage():
    line = ('{"id":"a","name":"/a","image":"i","state":"running","health":null,'
            '"restartCount":0,"labels":null,"startedAt":"x"}')
    cs = parse_inspect_lines(line + "\nError: No such object: x\n\n")
    assert len(cs) == 1
    assert cs[0].name == "a" and cs[0].labels == {} and cs[0].health is None


def test_inspect_format_tolerates_missing_health():
    # Docker 29 errors on `{{if .State.Health}}` when the key is absent.
    assert "index .State \"Health\"" in INSPECT_FORMAT
    assert INSPECT_COMMAND.startswith("docker ps -aq --no-trunc | xargs -r docker inspect --format '")


def test_parse_summary_full():
    h = parse_summary(load_json("summary_full.json"))
    assert h.disk_root_percent == 32.8
    assert h.disk_total == 80307429376
    assert h.cpu_percent == 23.5
    assert h.mem_percent == 45.0 and h.mem_total == 8589934592 and h.mem_used == 3865470566
    assert (h.load1, h.load5, h.load15) == (0.42, 0.36, 0.30)


def test_parse_summary_metrics_off():
    h = parse_summary(load_json("summary_metrics_off.json"))
    assert h.cpu_percent is None
    assert h.mem_percent is None
    assert h.load1 is None
    assert isinstance(h.disk_root_percent, float)


def test_parse_summary_no_root_disk():
    h = parse_summary({"disk": [{"mount": "/boot", "usedPercent": 5.0}]})
    assert h.disk_root_percent is None


def test_container_cpu_percent_string():
    m = parse_container_metrics(load_json("containers_current_full.json"))
    assert m["coolify-proxy"].cpu_percent == 12.5
    assert m["langfuse"].cpu_percent == 3.25
    assert m["langfuse"].mem_used == 314572800
    assert m["langfuse"].mem_percent == 3.66
    assert m["stopped-one"].cpu_percent is None and m["stopped-one"].mem_used is None


def test_container_metrics_off_fixture():
    m = parse_container_metrics(load_json("containers_current_metrics_off.json"))
    assert m and all(v.cpu_percent is None for v in m.values())


def test_display_name_prefers_coolify_name():
    base = dict(id="x", image="i", state="running", health=None, restart_count=0, started_at=None)
    assert display_name(ContainerInfo(name="abc-123", labels={"coolify.name": "abc"}, **base)) == "abc"
    assert display_name(ContainerInfo(name="abc-123", labels={"coolify.name": ""}, **base)) == "abc-123"
    assert display_name(ContainerInfo(name="abc-123", labels={}, **base)) == "abc-123"


def test_grouping_reexports_display_name():
    from fleetview import grouping
    assert grouping.display_name is display_name
