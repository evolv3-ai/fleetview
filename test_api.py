"""Quick test of sentinel /api/containers and /api/disk endpoints."""
import httpx

TOKEN = "d5e2bc55173305d524d68c3694f69d9681a28dc18240f313b3499f229cb3120d"
SERVERS = [
    ("contabo-kasm-01", "217.216.90.110"),
    ("hetzner-kasm-01", "5.161.200.197"),
    ("hetzner-kasm-02", "5.161.190.250"),
    ("hetzner-coolify-01", "178.156.152.51"),
    ("hetzner-coolify-02", "5.161.113.213"),
    ("C1", "147.93.137.67"),
]

headers = {"Authorization": f"Bearer {TOKEN}"}
client = httpx.Client(timeout=5.0)

for name, ip in SERVERS:
    try:
        cr = client.get(f"http://{ip}:8888/api/containers", headers=headers)
        dr = client.get(f"http://{ip}:8888/api/disk", headers=headers)
        containers = cr.json() if cr.status_code == 200 else []
        disk = dr.json() if dr.status_code == 200 else {}
        pct = disk.get("usedPercent", 0)
        print(f"{name}: containers={len(containers)} disk={pct:.1f}%")
    except Exception as e:
        print(f"{name}: FAILED - {e}")
