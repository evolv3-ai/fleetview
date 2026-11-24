import pytest

from fleetview.config_loader import ConfigError, load_config

VALID = '''
SERVERS = [
    {"id": "cbo-03-85-228", "ip": "85.239.242.228", "ssh_user": "admin",
     "ssh_key": "~/.ssh/id_ed25519_cbo-03", "sentinel_mode": "coolify",
     "sentinel_container": "coolify-sentinel", "provider": "Contabo", "role": "Coolify"},
    {"id": "htz-05-178-97", "ip": "178.156.187.97", "ssh_user": "root",
     "ssh_key": "~/.ssh/id_ed25519_htz-05", "sentinel_container": "fleet-sentinel"},
]
REFRESH_INTERVAL = 7
INVENTORY_INTERVAL = 90
THRESHOLDS = {"cpu_warn": 50, "cpu_crit": 80, "mem_warn": 70, "mem_crit": 90, "disk_warn": 70, "disk_crit": 90}
'''

LEGACY = '''
SENTINEL_TOKEN = "abc"
SERVERS = [{"id": "x", "ip": "1.2.3.4", "ssh_key": "~/.ssh/k"}]
CONNECTION_MODE = "tunnel"
'''


def _write(tmp_path, text):
    p = tmp_path / "config.py"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_valid(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert [s.id for s in cfg.servers] == ["cbo-03-85-228", "htz-05-178-97"]
    assert cfg.servers[0].ssh_user == "admin"
    assert cfg.servers[0].provider == "Contabo"
    assert cfg.servers[1].sentinel_mode == "standalone"
    assert cfg.refresh_interval == 7 and cfg.inventory_interval == 90
    assert cfg.thresholds["cpu_warn"] == 50


def test_load_config_rejects_legacy(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, LEGACY))
    assert str(e.value) == ("config.py is the old HTTP format; regenerate it with "
                            "D:/devops-native/scripts/profile-to-fleetview.py")


def test_load_config_missing_key(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, 'SERVERS = [{"id": "x", "ip": "1", "ssh_user": "root", "ssh_key": "k"}]'))
    assert "sentinel_container" in str(e.value) and "x" in str(e.value)


def test_load_config_env_and_missing_file(tmp_path, monkeypatch):
    p = _write(tmp_path, VALID)
    monkeypatch.setenv("FLEETVIEW_CONFIG", str(p))
    assert len(load_config().servers) == 2
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.py")


def test_shipped_example_config_loads():
    from pathlib import Path
    example = Path(__file__).parent.parent / "config.example.py"
    cfg = load_config(example)
    assert cfg.servers and all(s.sentinel_container for s in cfg.servers)
    assert "TOKEN" not in example.read_text(encoding="utf-8")
