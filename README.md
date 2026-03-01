# FleetView

Terminal dashboard for monitoring servers running [Sentinel](https://github.com/evolv3-ai/sentinel) agents. Built with [Textual](https://textual.textualize.io/).

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)

## Features

- Real-time CPU, memory, and disk monitoring with color-coded bars
- Docker container health overview per server
- SSH tunnel mode for firewalled sentinel instances
- Domain display per server (wildcard for Coolify, FQDN for KASM, etc.)
- Press `o` to open a server's management panel in your browser

## Quick Start

```bash
# Clone
git clone https://github.com/evolv3-ai/fleetview.git
cd fleetview

# Install dependencies
pip install -r requirements.txt

# Configure your servers
cp config.example.py config.py
# Edit config.py with your server IPs, SSH keys, and sentinel token

# Run
python app.py
```

## Keybindings

| Key | Action |
|-----|--------|
| `j` / `k` | Navigate servers |
| `o` | Open server management URL in browser |
| `r` | Force refresh |
| `q` | Quit |

## Configuration

Copy `config.example.py` to `config.py` and configure:

- **SENTINEL_TOKEN** -- must match the token on your sentinel instances
- **SERVERS** -- list of servers with IP, SSH key, provider, role, domain, and URL
- **CONNECTION_MODE** -- `"tunnel"` (SSH tunnels, recommended) or `"direct"` (direct IP access)
- **THRESHOLDS** -- CPU/MEM/DSK warning and critical percentages

Each server entry supports:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique identifier |
| `name` | yes | Display name |
| `ip` | yes | Server IP address |
| `provider` | yes | Cloud provider (Hetzner, Contabo, etc.) |
| `role` | yes | Server role (KASM, Coolify, Web, etc.) |
| `specs` | yes | Hardware specs string |
| `ssh_key` | yes | Path to SSH private key |
| `domain` | no | Domain shown in dashboard (e.g., `*.example.com`) |
| `url` | no | URL opened by `o` hotkey |

## Requirements

- Python 3.11+
- [Sentinel](https://github.com/evolv3-ai/sentinel) running on target servers (port 8888)
- SSH access to servers (for tunnel mode)
