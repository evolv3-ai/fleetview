"""Fleet configuration for FleetView (SSH mode).

Copy this file to config.py and fill in your servers, or generate it from the
device profile:
    python D:/devops-native/scripts/profile-to-fleetview.py > config.py

FleetView reads each server's Sentinel over SSH (`docker exec <container> curl ...`)
with the token already inside that container, so no token belongs in this file.
"""

SERVERS = [
    {
        "id": "web-01",
        "ip": "192.0.2.10",
        "ssh_user": "root",              # non-root users need passwordless sudo
        "ssh_key": "~/.ssh/id_ed25519",
        "sentinel_mode": "coolify",      # "coolify" or "standalone"
        "sentinel_container": "coolify-sentinel",  # or "fleet-sentinel"
        "provider": "Hetzner",
        "role": "Coolify",
        "specs": "4 vCPU / 8 GB",
        "domain": "example.com",
        "url": "https://coolify.example.com",
    },
    # Add more servers here...
]

# Seconds between metric polls / between docker inventory refreshes
REFRESH_INTERVAL = 5
INVENTORY_INTERVAL = 60

# Thresholds for color coding
THRESHOLDS = {
    "cpu_warn": 70,
    "cpu_crit": 90,
    "mem_warn": 70,
    "mem_crit": 90,
    "disk_warn": 70,
    "disk_crit": 90,
}
