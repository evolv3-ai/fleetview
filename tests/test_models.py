import pytest

from fleetview.models import HostMetrics, ServerConfig, ServerSnapshot


def _server(user="root"):
    return ServerConfig(
        id="cbo-03-85-228", ip="85.239.242.228", ssh_user=user,
        ssh_key="~/.ssh/id_ed25519_cbo-03", sentinel_mode="coolify",
        sentinel_container="coolify-sentinel",
    )


def _host(cpu=1.0, mem=2.0, disk=3.0):
    return HostMetrics(
        cpu_percent=cpu, mem_total=None, mem_used=None, mem_percent=mem,
        disk_total=None, disk_used=None, disk_root_percent=disk,
        load1=None, load5=None, load15=None,
    )


def test_online_requires_health_and_three_metrics():
    s = _server()
    assert ServerSnapshot(server=s, health="ok", host=_host()).online is True
    assert ServerSnapshot(server=s, health="ok", host=_host(cpu=None)).online is False
    assert ServerSnapshot(server=s, health="ok", host=_host(mem=None)).online is False
    assert ServerSnapshot(server=s, health="ok", host=_host(disk=None)).online is False
    assert ServerSnapshot(server=s, health="degraded", host=_host()).online is False
    assert ServerSnapshot(server=s, health="ok", host=None).online is False


def test_base_url_format():
    snap = ServerSnapshot(server=_server("admin"))
    assert snap.base_url == "ssh://admin@85.239.242.228/coolify-sentinel"


def test_snapshot_defaults_are_independent():
    a, b = ServerSnapshot(server=_server()), ServerSnapshot(server=_server())
    a.containers.append(object())
    assert b.containers == []
