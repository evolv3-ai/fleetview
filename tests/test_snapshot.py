import asyncio
import json
from datetime import datetime, timezone

from fleetview.collector import ServerCollector
from fleetview.snapshot import build_snapshot, write_snapshot

from .fakes import FakeRunner, fixture_responses, server

STACK_KEYS = {"kind", "project", "environment", "resource", "coolifyUuid", "domains",
              "workingDir", "platform", "containers"}
CONTAINER_KEYS = {"name", "image", "state", "health", "restartCount"}


def _snaps():
    fake = FakeRunner(fixture_responses(inspect="inspect_htz03.jsonl"))
    return [asyncio.run(ServerCollector(server("htz-03-178-51"), runner_factory=lambda s: fake).poll(True))]


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_snapshot_shape():
    gen = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    data = build_snapshot(_snaps(), gen)
    assert set(data) == {"generatedAt", "servers"}
    assert data["generatedAt"].startswith("2026-11-23T12:00:00")
    srv = data["servers"]["htz-03-178-51"]
    assert set(srv) == {"fetchedAt", "sentinel", "stacks"}
    assert srv["sentinel"] == {"mode": "coolify", "version": "1.1.5"}
    lf = srv["stacks"]["e14got5549ldxlaqmz23d7fi"]
    assert set(lf) == STACK_KEYS
    assert lf["kind"] == "coolify-service" and lf["coolifyUuid"] == "e14got5549ldxlaqmz23d7fi"
    assert lf["platform"] is False
    for st in srv["stacks"].values():
        assert set(st) == STACK_KEYS
        for c in st["containers"]:
            assert set(c) == CONTAINER_KEYS
    assert srv["stacks"]["coolify-proxy"]["platform"] is True
    assert "labels" not in set(_walk_keys(data))
    json.dumps(data)


def test_snapshot_skips_server_without_inventory():
    from fleetview.models import ServerSnapshot
    data = build_snapshot([ServerSnapshot(server=server(), error="auth failed")],
                          datetime.now(timezone.utc))
    assert data["servers"] == {}


def test_write_snapshot_atomic(tmp_path):
    path = tmp_path / "gen" / "fleet-containers.json"
    write_snapshot(path, {"a": 1})
    write_snapshot(path, {"b": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"b": 2}
    assert list(path.parent.iterdir()) == [path]
