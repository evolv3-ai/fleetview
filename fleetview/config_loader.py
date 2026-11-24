"""Load the generated config.py into a FleetConfig."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .models import FleetConfig, ServerConfig, _default_thresholds

REQUIRED_KEYS = ("id", "ip", "ssh_user", "ssh_key", "sentinel_container")
LEGACY_MESSAGE = (
    "config.py is the old HTTP format; regenerate it with "
    "D:/devops-native/scripts/profile-to-fleetview.py"
)
_OPTIONAL = ("provider", "role", "specs", "domain", "url")


class ConfigError(Exception):
    pass


def _resolve(path: Path | None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("FLEETVIEW_CONFIG")
    if env:
        return Path(env)
    return Path.cwd() / "config.py"


def load_config(path: Path | None = None) -> FleetConfig:
    p = _resolve(path)
    if not p.is_file():
        raise ConfigError(f"config not found: {p}")
    spec = importlib.util.spec_from_file_location("fleetview_user_config", p)
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot load config: {p}")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # a broken config is a config error, not a crash
        raise ConfigError(f"error in {p}: {type(e).__name__}: {e}") from e

    raw = getattr(mod, "SERVERS", None)
    if not isinstance(raw, list):
        raise ConfigError(f"{p}: SERVERS must be a list")
    if hasattr(mod, "SENTINEL_TOKEN") and not any(
        isinstance(s, dict) and "sentinel_container" in s for s in raw
    ):
        raise ConfigError(LEGACY_MESSAGE)

    servers: list[ServerConfig] = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise ConfigError(f"{p}: SERVERS[{i}] is not a dict")
        missing = [k for k in REQUIRED_KEYS if not s.get(k)]
        if missing:
            raise ConfigError(f"{p}: server {s.get('id', i)!s} is missing {', '.join(missing)}")
        container = str(s["sentinel_container"])
        mode = s.get("sentinel_mode") or ("coolify" if container == "coolify-sentinel" else "standalone")
        servers.append(ServerConfig(
            id=str(s["id"]), ip=str(s["ip"]), ssh_user=str(s["ssh_user"]), ssh_key=str(s["ssh_key"]),
            sentinel_mode=str(mode), sentinel_container=container,
            **{k: str(s.get(k) or "") for k in _OPTIONAL},
        ))

    thresholds = _default_thresholds()
    thresholds.update(getattr(mod, "THRESHOLDS", None) or {})
    return FleetConfig(
        servers=servers,
        refresh_interval=int(getattr(mod, "REFRESH_INTERVAL", 5)),
        inventory_interval=int(getattr(mod, "INVENTORY_INTERVAL", 60)),
        thresholds=thresholds,
    )
