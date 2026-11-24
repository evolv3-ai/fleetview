# FleetView

Terminal dashboard and headless health checks for servers running the upstream Rust
[Sentinel](https://github.com/coollabsio/sentinel) (Coolify's own `coolify-sentinel`, or a
standalone `fleet-sentinel`). Built with [Textual](https://textual.textualize.io/) and
[asyncssh](https://asyncssh.readthedocs.io/).

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)

## How it works

FleetView keeps one SSH connection per server. Over it, it runs
`docker exec <sentinel-container> curl ...` against Sentinel's loopback API (the token is
read inside the container and never leaves the server) and `docker inspect` for container
labels. No Sentinel port needs to be published and no token is stored locally.

## Features

- CPU, memory, disk and load per server, color-coded (shows "metrics off" when Coolify's
  Metrics setting is disabled)
- Containers grouped by Coolify project / stack, with domains from Caddy and Traefik labels,
  and per-container CPU and memory
- Stopped and restart-looping containers highlighted
- `fleetview pull`: `sentinelctl pull`-compatible JSON and CI gate
- `fleetview snapshot` / `fleetview reconcile`: fleet container snapshot and drift report
- Press `o` to open a server's management panel in your browser

## Quick Start

```bash
uv sync

# Configure your servers (or generate from the profile, see config.example.py)
cp config.example.py config.py

uv run fleetview                      # TUI
uv run fleetview pull --ci            # JSON health pull, exit 1 if any gate fails
uv run fleetview snapshot             # ~/.admin/generated/fleet-containers.json
uv run fleetview reconcile            # drift report vs the profile
uv run pytest -q                      # tests
```

Hosts must already be in `~/.ssh/known_hosts`; FleetView never auto-accepts host keys.

## Keybindings

| Key | Action |
|-----|--------|
| `j` / `k` | Navigate servers |
| `o` | Open server management URL in browser |
| `r` | Force refresh (including container inventory) |
| `q` | Quit |

## Configuration

`config.py` is loaded from env `FLEETVIEW_CONFIG` if set, else `./config.py`:

- **SERVERS**: list of servers (fields below)
- **REFRESH_INTERVAL** / **INVENTORY_INTERVAL**: seconds between metric polls and docker inventory refreshes
- **THRESHOLDS**: CPU/MEM/DSK warning and critical percentages

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique identifier |
| `ip` | yes | Server IP address |
| `ssh_user` | yes | SSH user; non-root users get `sudo -n` (passwordless sudo required) |
| `ssh_key` | yes | Path to SSH private key |
| `sentinel_container` | yes | `coolify-sentinel` or `fleet-sentinel` |
| `sentinel_mode` | no | `coolify` or `standalone` (inferred from the container name) |
| `provider`, `role`, `specs` | no | Shown in the server panel |
| `domain` | no | Domain shown in dashboard |
| `url` | no | URL opened by `o` hotkey |

## Requirements

- Python 3.11+, uv
- Rust Sentinel 1.1.x in a container with `curl` on each server
- Key-based SSH access to each server
