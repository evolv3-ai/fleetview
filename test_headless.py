"""Headless test - verify SSH tunnels + sentinel API via tunnels."""
import subprocess
import sys
import time

import httpx

from config import SENTINEL_TOKEN, SERVERS, SSH_USER

TUNNEL_BASE_PORT = 18800
SSH_EXE = "C:/Windows/System32/OpenSSH/ssh.exe"

procs = []
print("Opening SSH tunnels...")
for i, srv in enumerate(SERVERS):
    local_port = TUNNEL_BASE_PORT + i
    ssh_key = srv.get("ssh_key", "~/.ssh/id_ed25519")
    cmd = [
        SSH_EXE, "-N",
        "-L", f"{local_port}:localhost:8888",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=5",
        "-o", "ExitOnForwardFailure=yes",
        "-i", ssh_key,
        f"{SSH_USER}@{srv['ip']}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(proc)
    print(f"  {srv['name']} -> 127.0.0.1:{local_port}")

print("Waiting 5s for tunnels...")
time.sleep(5)

headers = {"Authorization": f"Bearer {SENTINEL_TOKEN}"}
client = httpx.Client(timeout=5.0)
ok = 0
fail = 0

for i, srv in enumerate(SERVERS):
    port = TUNNEL_BASE_PORT + i
    base = f"http://127.0.0.1:{port}"
    try:
        cpu = client.get(f"{base}/api/cpu/current", headers=headers).json()
        mem = client.get(f"{base}/api/memory/current", headers=headers).json()
        disk = client.get(f"{base}/api/disk", headers=headers).json()
        containers = client.get(f"{base}/api/containers", headers=headers).json()
        print(
            f"  {srv['name']}: CPU={cpu.get('percent',0):.1f}% "
            f"MEM={mem.get('usedPercent',0):.1f}% "
            f"DSK={disk.get('usedPercent',0):.1f}% "
            f"Containers={len(containers)}"
        )
        ok += 1
    except Exception as e:
        print(f"  {srv['name']}: FAILED - {e}")
        fail += 1

print(f"\nResults: {ok} OK, {fail} FAILED")

for p in procs:
    p.terminate()
    try:
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        p.kill()

sys.exit(0 if fail == 0 else 1)
