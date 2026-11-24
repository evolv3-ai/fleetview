import json

import pytest

from fleetview import cli
from fleetview.collector import ServerCollector
from fleetview.models import FleetConfig

from .fakes import FakeRunner, fixture_responses, server

LEGACY = 'SENTINEL_TOKEN = "abc"\nSERVERS = [{"id": "x", "ip": "1.2.3.4", "ssh_key": "k"}]\n'


async def _fixture_snap(sid, health="healthy"):
    resp = fixture_responses()
    if health != "healthy":
        resp["docker ps"] = resp["docker ps"].__class__(
            0, resp["docker ps"].stdout.replace('"health":"healthy"', f'"health":"{health}"', 1), "")
    fake = FakeRunner(resp)
    return await ServerCollector(server(sid), runner_factory=lambda s: fake).poll(True)


@pytest.fixture
def fake_fleet(monkeypatch):
    state = {"health": "healthy", "closed": 0, "servers": None}
    cfg = FleetConfig(servers=[server("htz-04-5-213"), server("cbo-03-85-228", user="admin")])

    class FakeCollector:
        def __init__(self, c, runner_factory=None):
            state["servers"] = [s.id for s in c.servers]
            self.cfg = c

        async def poll(self, include_inventory):
            return [await _fixture_snap(s.id, state["health"]) for s in self.cfg.servers]

        async def close(self):
            state["closed"] += 1

    monkeypatch.setattr(cli, "FleetCollector", FakeCollector)
    monkeypatch.setattr(cli, "load_config", lambda path=None: cfg)
    return state


def test_cli_pull_deprecated_flags_warn(fake_fleet, capsys):
    assert cli.main(["pull", "--token", "x", "--config", "f.json", "--connection-mode", "direct"]) == 0
    out, err = capsys.readouterr()
    assert "fleetview pull: --config/--token/--connection-mode are ignored (SSH transport)" in err
    data = json.loads(out)
    assert [r["id"] for r in data["results"]] == ["htz-04-5-213", "cbo-03-85-228"]
    assert fake_fleet["closed"] == 1


def test_cli_pull_no_warning_without_legacy_flags(fake_fleet, capsys):
    assert cli.main(["pull"]) == 0
    assert capsys.readouterr().err == ""


def test_cli_pull_ci_exit_code(fake_fleet, capsys):
    # full-metrics fixture => online; make one container unhealthy => CI fails
    fake_fleet["health"] = "unhealthy"
    assert cli.main(["pull", "--ci"]) == 1
    fake_fleet["health"] = "healthy"
    assert cli.main(["pull", "--ci"]) == 0
    assert cli.main(["pull", "--ci", "--container-match", "no-such-container"]) == 1


def test_cli_pull_servers_filter_and_watch(fake_fleet, capsys, monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(cli.asyncio, "sleep", no_sleep)
    assert cli.main(["pull", "--servers", "cbo-03-85-228", "--watch-seconds", "1", "--iterations", "3"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 3
    assert [r["id"] for r in json.loads(lines[0])["results"]] == ["cbo-03-85-228"]
    assert fake_fleet["servers"] == ["cbo-03-85-228"]


def test_cli_snapshot_writes_file(fake_fleet, capsys, tmp_path):
    out = tmp_path / "s.json"
    assert cli.main(["snapshot", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["servers"]) == {"htz-04-5-213", "cbo-03-85-228"}
    printed = capsys.readouterr().out
    assert str(out) in printed and "stacks" in printed


def test_cli_reconcile_prints_report(tmp_path, capsys):
    snap = tmp_path / "s.json"
    prof = tmp_path / "p.json"
    snap.write_text(json.dumps({"generatedAt": "x", "servers": {}}), encoding="utf-8")
    prof.write_text(json.dumps({"servers": [], "deployments": {}}), encoding="utf-8")
    assert cli.main(["reconcile", "--snapshot", str(snap), "--profile", str(prof)]) == 0
    assert "Untracked stacks (0)" in capsys.readouterr().out


def test_cli_legacy_config_returns_2(tmp_path, monkeypatch, capsys):
    p = tmp_path / "config.py"
    p.write_text(LEGACY, encoding="utf-8")
    monkeypatch.setenv("FLEETVIEW_CONFIG", str(p))
    assert cli.main(["pull"]) == 2
    assert "old HTTP format" in capsys.readouterr().err
