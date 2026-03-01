"""Fleet configuration for FleetView dashboard.

Copy this file to config.py and fill in your server details:
    cp config.example.py config.py
"""

# Sentinel API token (must match the token on your sentinel instances)
SENTINEL_TOKEN = "your-sentinel-token-here"

# SSH key paths (used for tunnel mode)
SSH_KEY_ED25519 = "~/.ssh/id_ed25519"
SSH_KEY_RSA = "~/.ssh/id_rsa"

SERVERS = [
    {
        "id": "web-01",
        "name": "web-01",
        "ip": "192.168.1.10",
        "provider": "Hetzner",
        "role": "Web",
        "specs": "4 vCPU / 8 GB",
        "ssh_key": SSH_KEY_ED25519,
        "domain": "example.com",
        "url": "https://example.com",
    },
    # Add more servers here...
]

# Connection mode: "direct" polls IPs directly, "tunnel" uses SSH tunnels
# Port 8888 is typically firewalled; use tunnel mode from local machines
# or direct mode when running on one of the servers
CONNECTION_MODE = "tunnel"

# SSH tunnel config (used when CONNECTION_MODE == "tunnel")
SSH_USER = "root"

# Refresh interval in seconds
REFRESH_INTERVAL = 5

# Thresholds for color coding
THRESHOLDS = {
    "cpu_warn": 70,
    "cpu_crit": 90,
    "mem_warn": 70,
    "mem_crit": 90,
    "disk_warn": 70,
    "disk_crit": 90,
}
