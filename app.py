"""Sentinel Fleet Dashboard - Python Textual TUI."""

import asyncio
import subprocess
import sys
import webbrowser
from datetime import datetime

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Static

from config import (
    CONNECTION_MODE,
    REFRESH_INTERVAL,
    SENTINEL_TOKEN,
    SERVERS,
    SSH_USER,
    THRESHOLDS,
)

TUNNEL_BASE_PORT = 18800


def fmt_bytes(b: float) -> str:
    """Format bytes to human-readable."""
    if b < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def severity_color(value: float, warn: float, crit: float) -> str:
    """Return color name based on threshold."""
    if value >= crit:
        return "red"
    if value >= warn:
        return "yellow"
    return "green"


class ServerData:
    """Holds fetched metrics for one server."""

    def __init__(self, server_cfg: dict):
        self.cfg = server_cfg
        self.online = False
        self.cpu_pct: float = 0.0
        self.mem_total: float = 0
        self.mem_used: float = 0
        self.mem_pct: float = 0.0
        self.disk_total: float = 0
        self.disk_used: float = 0
        self.disk_pct: float = 0.0
        self.containers: list[dict] = []
        self.error: str = ""
        self.last_update: datetime | None = None


class FleetSummary(Static):
    """Top-level fleet summary bar."""

    fleet_text = reactive("")

    def render(self) -> str:
        return self.fleet_text


class ServerPanel(Static):
    """Compact panel for one server in the fleet overview."""

    def __init__(self, server_id: str, **kwargs):
        super().__init__(**kwargs)
        self.server_id = server_id
        self._data: ServerData | None = None

    def update_data(self, data: ServerData) -> None:
        self._data = data
        self.refresh()

    def render(self) -> str:
        d = self._data
        if d is None:
            return f"[dim]{self.server_id}[/dim]\n  Loading..."

        cfg = d.cfg
        name = cfg["id"]
        role = cfg["role"]

        domain = cfg.get("domain", "")
        domain_url = cfg.get("domain_url", "")

        if not d.online:
            err = d.error[:40] if d.error else "unreachable"
            domain_tag = f" [dim]{domain}[/dim]" if domain else ""
            return f"[bold red]{name}[/bold red] [{role}]{domain_tag}\n  [red]OFFLINE[/red] {err}"

        cpu_c = severity_color(d.cpu_pct, THRESHOLDS["cpu_warn"], THRESHOLDS["cpu_crit"])
        mem_c = severity_color(d.mem_pct, THRESHOLDS["mem_warn"], THRESHOLDS["mem_crit"])
        disk_c = severity_color(d.disk_pct, THRESHOLDS["disk_warn"], THRESHOLDS["disk_crit"])

        cpu_bar = self._bar(d.cpu_pct)
        mem_bar = self._bar(d.mem_pct)
        disk_bar = self._bar(d.disk_pct)

        n_containers = len(d.containers)
        running = sum(1 for c in d.containers if c.get("state") == "running")
        healthy = sum(1 for c in d.containers if c.get("health_status") == "healthy")
        unhealthy = sum(
            1 for c in d.containers
            if c.get("state") == "running" and c.get("health_status") not in ("healthy", "unknown", "")
        )

        container_info = f"{running}/{n_containers} running"
        if healthy > 0:
            container_info += f" [green]{healthy} healthy[/green]"
        if unhealthy > 0:
            container_info += f" [red]{unhealthy} unhealthy[/red]"

        if domain:
            domain_display = f" [cyan]{domain}[/cyan]"
        else:
            domain_display = ""

        lines = [
            f"[bold]{name}[/bold] [{role}]{domain_display} {cfg['specs']}",
            f"  CPU [{cpu_c}]{cpu_bar} {d.cpu_pct:5.1f}%[/{cpu_c}]  "
            f"MEM [{mem_c}]{mem_bar} {d.mem_pct:5.1f}%[/{mem_c}] "
            f"({fmt_bytes(d.mem_used)}/{fmt_bytes(d.mem_total)})",
            f"  DSK [{disk_c}]{disk_bar} {d.disk_pct:5.1f}%[/{disk_c}] "
            f"({fmt_bytes(d.disk_used)}/{fmt_bytes(d.disk_total)})  "
            f"{container_info}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _bar(pct: float, width: int = 15) -> str:
        filled = int(pct / 100 * width)
        return "[" + "#" * filled + "-" * (width - filled) + "]"


class ContainerTable(DataTable):
    """Table showing containers for the selected server."""
    pass


class TunnelManager:
    """Manages SSH tunnels to sentinel instances."""

    def __init__(self, servers: list[dict]):
        self._procs: list[subprocess.Popen] = []
        self._port_map: dict[str, int] = {}
        for i, srv in enumerate(servers):
            self._port_map[srv["id"]] = TUNNEL_BASE_PORT + i

    def start(self) -> None:
        ssh_exe = "C:/Windows/System32/OpenSSH/ssh.exe" if sys.platform == "win32" else "ssh"
        for srv in SERVERS:
            local_port = self._port_map[srv["id"]]
            ssh_key = srv.get("ssh_key", "~/.ssh/id_ed25519")
            cmd = [
                ssh_exe,
                "-N", "-L", f"{local_port}:localhost:8888",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=5",
                "-o", "ServerAliveInterval=30",
                "-o", "ExitOnForwardFailure=yes",
                "-i", ssh_key,
                f"{SSH_USER}@{srv['ip']}",
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._procs.append(proc)
            except Exception:
                self._procs.append(None)

    def stop(self) -> None:
        for proc in self._procs:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._procs.clear()

    def base_url(self, server_id: str) -> str:
        port = self._port_map.get(server_id, 8888)
        return f"http://127.0.0.1:{port}"


class SentinelDashboard(App):
    """Fleet monitoring dashboard powered by Sentinel."""

    TITLE = "Sentinel Fleet Dashboard"
    CSS = """
    Screen {
        layout: vertical;
    }
    #fleet-summary {
        height: 3;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    #main-area {
        height: 1fr;
    }
    #server-list {
        width: 1fr;
        min-width: 60;
        border-right: solid $primary;
    }
    #detail-panel {
        width: 1fr;
        min-width: 50;
        padding: 0 1;
    }
    .server-panel {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $surface-lighten-2;
    }
    .server-panel:hover {
        border: solid $primary;
    }
    .server-panel.selected {
        border: double $primary;
        background: $surface-lighten-1;
    }
    #detail-header {
        height: 3;
        padding: 0 1;
        background: $surface-lighten-1;
    }
    #container-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("j", "next_server", "Next"),
        Binding("k", "prev_server", "Prev"),
        Binding("o", "open_server", "Open"),
    ]

    selected_index = reactive(0)

    def __init__(self):
        super().__init__()
        self._server_data: dict[str, ServerData] = {}
        self._panels: dict[str, ServerPanel] = {}
        self._client = httpx.AsyncClient(timeout=5.0)
        self._refresh_timer: Timer | None = None
        self._tunnels: TunnelManager | None = None

        for srv in SERVERS:
            self._server_data[srv["id"]] = ServerData(srv)

        if CONNECTION_MODE == "tunnel":
            self._tunnels = TunnelManager(SERVERS)
            self._tunnels.start()

    def compose(self) -> ComposeResult:
        yield Header()
        yield FleetSummary(id="fleet-summary")
        with Horizontal(id="main-area"):
            with VerticalScroll(id="server-list"):
                for srv in SERVERS:
                    panel = ServerPanel(srv["id"], classes="server-panel")
                    self._panels[srv["id"]] = panel
                    yield panel
            with Vertical(id="detail-panel"):
                yield Static("Select a server", id="detail-header")
                yield ContainerTable(id="container-table")
        yield Footer()

    def on_mount(self) -> None:
        self._update_selection()
        table = self.query_one("#container-table", ContainerTable)
        table.add_columns("Name", "Image", "State", "Health")
        # Give SSH tunnels a moment to establish
        delay = 3 if CONNECTION_MODE == "tunnel" else 0
        self._refresh_timer = self.set_interval(REFRESH_INTERVAL, self._poll_all)
        if delay:
            self.set_timer(delay, lambda: self.run_worker(self._poll_all()))
        else:
            self.run_worker(self._poll_all())

    def watch_selected_index(self, old: int, new: int) -> None:
        self._update_selection()
        self._update_detail()

    def _update_selection(self) -> None:
        for i, srv in enumerate(SERVERS):
            panel = self._panels[srv["id"]]
            if i == self.selected_index:
                panel.add_class("selected")
            else:
                panel.remove_class("selected")

    def action_next_server(self) -> None:
        self.selected_index = (self.selected_index + 1) % len(SERVERS)

    def action_prev_server(self) -> None:
        self.selected_index = (self.selected_index - 1) % len(SERVERS)

    def action_open_server(self) -> None:
        if not SERVERS:
            return
        srv = SERVERS[self.selected_index]
        url = srv.get("url", "")
        if url:
            webbrowser.open(url)
            self.notify(f"Opening {url}")
        else:
            self.notify(f"No URL configured for {srv['id']}", severity="warning")

    def action_refresh(self) -> None:
        self.run_worker(self._poll_all())

    async def _poll_all(self) -> None:
        tasks = [self._poll_server(srv) for srv in SERVERS]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._update_fleet_summary()
        for srv in SERVERS:
            panel = self._panels[srv["id"]]
            panel.update_data(self._server_data[srv["id"]])
        self._update_detail()

    def _get_base_url(self, srv: dict) -> str:
        if self._tunnels:
            return self._tunnels.base_url(srv["id"])
        return f"http://{srv['ip']}:8888"

    async def _poll_server(self, srv: dict) -> None:
        data = self._server_data[srv["id"]]
        base = self._get_base_url(srv)
        headers = {"Authorization": f"Bearer {SENTINEL_TOKEN}"}

        try:
            cpu_resp, mem_resp, disk_resp, containers_resp = await asyncio.gather(
                self._client.get(f"{base}/api/cpu/current", headers=headers),
                self._client.get(f"{base}/api/memory/current", headers=headers),
                self._client.get(f"{base}/api/disk", headers=headers),
                self._client.get(f"{base}/api/containers", headers=headers),
            )

            if cpu_resp.status_code == 200:
                cpu_json = cpu_resp.json()
                data.cpu_pct = cpu_json.get("percent", 0.0)

            if mem_resp.status_code == 200:
                mem_json = mem_resp.json()
                data.mem_total = mem_json.get("total", 0)
                data.mem_used = mem_json.get("used", 0)
                data.mem_pct = mem_json.get("usedPercent", 0.0)

            if disk_resp.status_code == 200:
                disk_json = disk_resp.json()
                data.disk_total = disk_json.get("total", 0)
                data.disk_used = disk_json.get("used", 0)
                data.disk_pct = disk_json.get("usedPercent", 0.0)

            if containers_resp.status_code == 200:
                data.containers = containers_resp.json() or []

            data.online = True
            data.error = ""
            data.last_update = datetime.now()

        except Exception as e:
            data.online = False
            data.error = str(e)[:60]

    def _update_fleet_summary(self) -> None:
        total = len(SERVERS)
        online = sum(1 for d in self._server_data.values() if d.online)
        offline = total - online

        avg_cpu = 0.0
        avg_mem = 0.0
        avg_disk = 0.0
        total_containers = 0
        count = 0
        for d in self._server_data.values():
            if d.online:
                avg_cpu += d.cpu_pct
                avg_mem += d.mem_pct
                avg_disk += d.disk_pct
                total_containers += len(d.containers)
                count += 1
        if count > 0:
            avg_cpu /= count
            avg_mem /= count
            avg_disk /= count

        cpu_c = severity_color(avg_cpu, THRESHOLDS["cpu_warn"], THRESHOLDS["cpu_crit"])
        mem_c = severity_color(avg_mem, THRESHOLDS["mem_warn"], THRESHOLDS["mem_crit"])
        disk_c = severity_color(avg_disk, THRESHOLDS["disk_warn"], THRESHOLDS["disk_crit"])

        now = datetime.now().strftime("%H:%M:%S")
        summary = self.query_one("#fleet-summary", FleetSummary)
        text = (
            f"Fleet: [bold green]{online}[/bold green]/{total} online"
        )
        if offline:
            text += f"  [bold red]{offline} offline[/bold red]"
        text += (
            f"  |  CPU: [{cpu_c}]{avg_cpu:.1f}%[/{cpu_c}]"
            f"  MEM: [{mem_c}]{avg_mem:.1f}%[/{mem_c}]"
            f"  DSK: [{disk_c}]{avg_disk:.1f}%[/{disk_c}]"
            f"  |  {total_containers} containers"
            f"  |  {now}"
        )
        summary.fleet_text = text

    def _update_detail(self) -> None:
        if not SERVERS:
            return
        srv = SERVERS[self.selected_index]
        data = self._server_data[srv["id"]]

        header = self.query_one("#detail-header", Static)
        domain = srv.get("domain", "")

        if domain:
            domain_tag = f" [cyan]{domain}[/cyan]"
        else:
            domain_tag = ""

        if not data.online:
            header.update(
                f"[bold]{srv['id']}[/bold] ({srv['ip']}){domain_tag} - "
                f"[red]OFFLINE[/red]"
            )
            table = self.query_one("#container-table", ContainerTable)
            table.clear()
            return

        disk_c = severity_color(data.disk_pct, THRESHOLDS["disk_warn"], THRESHOLDS["disk_crit"])
        header.update(
            f"[bold]{srv['id']}[/bold] ({srv['ip']}){domain_tag} - "
            f"{srv['provider']} / {srv['role']} / {srv['specs']}\n"
            f"CPU: {data.cpu_pct:.1f}%  MEM: {data.mem_pct:.1f}% "
            f"({fmt_bytes(data.mem_used)}/{fmt_bytes(data.mem_total)})  "
            f"DSK: [{disk_c}]{data.disk_pct:.1f}%[/{disk_c}] "
            f"({fmt_bytes(data.disk_used)}/{fmt_bytes(data.disk_total)})"
        )

        table = self.query_one("#container-table", ContainerTable)
        table.clear()
        for c in data.containers:
            state = c.get("state", "?")
            health = c.get("health_status", "n/a")
            image = c.get("image", "?")
            if len(image) > 40:
                image = image[:37] + "..."
            table.add_row(
                c.get("name", c.get("id", "?")[:12]),
                image,
                state,
                health,
            )

    async def on_unmount(self) -> None:
        await self._client.aclose()
        if self._tunnels:
            self._tunnels.stop()


if __name__ == "__main__":
    app = SentinelDashboard()
    app.run()
