"""Sentinel Fleet Dashboard - Textual TUI reading Rust Sentinel over SSH."""
from __future__ import annotations

import asyncio
import time
import webbrowser
from datetime import datetime

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static

from .grouping import display_name
from .models import FleetConfig, ServerSnapshot

STATE_STYLES = {"exited": "bold red", "dead": "bold red", "restarting": "bold yellow",
                "created": "yellow", "paused": "yellow"}
HEALTH_STYLES = {"healthy": "green", "unhealthy": "bold red", "starting": "yellow"}
COLUMNS = ("Name", "Project", "Stack", "State", "Health", "CPU%", "MEM", "Domain", "Image")


def fmt_bytes(b: float | int | None) -> str:
    """Format bytes to human-readable."""
    if b is None or b < 0:
        return "?"
    b = float(b)
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


def _bar(pct: float, width: int = 15) -> str:
    filled = max(0, min(width, int(pct / 100 * width)))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _metric(label: str, pct, warn: int, crit: int, extra: str = "") -> str:
    if pct is None:
        return f"{label} [dim]n/a[/dim]"
    c = severity_color(pct, warn, crit)
    return f"{label} [{c}]{escape(_bar(pct))} {pct:5.1f}%[/{c}]{extra}"


def _metrics_off(s: ServerSnapshot) -> bool:
    return s.health == "ok" and s.host is not None and s.host.cpu_percent is None


def _container_counts(s: ServerSnapshot) -> str:
    total = len(s.containers)
    running = sum(1 for c in s.containers if c.state == "running")
    healthy = sum(1 for c in s.containers if c.state == "running" and c.health == "healthy")
    bad = sum(1 for c in s.containers
              if c.state == "running" and (c.health or "unknown") not in ("healthy", "unknown"))
    looping = sum(1 for c in s.containers if c.state in ("restarting", "exited", "dead"))
    info = f"{running}/{total} running"
    if healthy:
        info += f" [green]{healthy} healthy[/green]"
    if bad:
        info += f" [red]{bad} unhealthy[/red]"
    if looping:
        info += f" [yellow]{looping} stopped/restarting[/yellow]"
    return info


class FleetSummary(Static):
    """Top-level fleet summary bar."""

    fleet_text = reactive("")

    def render(self) -> str:
        return self.fleet_text


class ServerPanel(Static):
    """Compact panel for one server in the fleet overview."""

    def __init__(self, cfg: FleetConfig, server_id: str, **kwargs):
        super().__init__(**kwargs)
        self.cfg = cfg
        self.server_id = server_id
        self._snap: ServerSnapshot | None = None

    def update_data(self, snap: ServerSnapshot) -> None:
        self._snap = snap
        self.refresh()

    def render(self) -> str:
        s = self._snap
        if s is None:
            return f"[dim]{self.server_id}[/dim]\n  Loading..."
        srv = s.server
        t = self.cfg.thresholds
        domain = f" [cyan]{escape(srv.domain)}[/cyan]" if srv.domain else ""
        head = f"[bold]{srv.id}[/bold] \\[{escape(srv.role)}]{domain} {escape(srv.specs)}"
        if s.host is None:
            err = escape((s.error or "unreachable")[:60])
            return f"[bold red]{srv.id}[/bold red] \\[{escape(srv.role)}]{domain}\n  [red]OFFLINE[/red] {err}"
        h = s.host
        lines = [head]
        if _metrics_off(s):
            lines.append("  [yellow]metrics off[/yellow] (enable Metrics in Coolify)")
        else:
            mem_extra = f" ({fmt_bytes(h.mem_used)}/{fmt_bytes(h.mem_total)})" if h.mem_total else ""
            lines.append("  " + _metric("CPU", h.cpu_percent, t["cpu_warn"], t["cpu_crit"]) + "  "
                         + _metric("MEM", h.mem_percent, t["mem_warn"], t["mem_crit"], mem_extra))
        dsk_extra = f" ({fmt_bytes(h.disk_used)}/{fmt_bytes(h.disk_total)})" if h.disk_total else ""
        lines.append("  " + _metric("DSK", h.disk_root_percent, t["disk_warn"], t["disk_crit"], dsk_extra)
                     + "  " + _container_counts(s))
        if h.load1 is not None:
            lines.append(f"  load {h.load1:.2f} {h.load5 or 0:.2f} {h.load15 or 0:.2f}")
        if s.error:
            lines.append(f"  [red]{escape(s.error[:80])}[/red]")
        return "\n".join(lines)


class ContainerTable(DataTable):
    """Table showing containers for the selected server."""


class SentinelDashboard(App):
    """Fleet monitoring dashboard powered by Sentinel over SSH."""

    TITLE = "Sentinel Fleet Dashboard"
    CSS = """
    Screen { layout: vertical; }
    #fleet-summary { height: 3; background: $surface; padding: 0 1; border-bottom: solid $primary; }
    #main-area { height: 1fr; }
    #server-list { width: 1fr; min-width: 60; border-right: solid $primary; }
    #detail-panel { width: 2fr; min-width: 50; padding: 0 1; }
    .server-panel { height: auto; padding: 0 1; margin: 0 0 1 0; border: solid $surface-lighten-2; }
    .server-panel:hover { border: solid $primary; }
    .server-panel.selected { border: double $primary; background: $surface-lighten-1; }
    #detail-header { height: 3; padding: 0 1; background: $surface-lighten-1; }
    #container-table { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("j", "next_server", "Next"),
        Binding("k", "prev_server", "Prev"),
        Binding("o", "open_server", "Open"),
    ]

    selected_index = reactive(0)

    def __init__(self, cfg: FleetConfig, collector):
        super().__init__()
        self.cfg = cfg
        self.collector = collector
        self._snaps: dict[str, ServerSnapshot] = {}
        self._panels: dict[str, ServerPanel] = {}
        self._last_inventory: dict[str, float] = {}
        self._inflight: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield FleetSummary(id="fleet-summary")
        with Horizontal(id="main-area"):
            with VerticalScroll(id="server-list"):
                for srv in self.cfg.servers:
                    panel = ServerPanel(self.cfg, srv.id, classes="server-panel", id=f"panel-{srv.id}")
                    self._panels[srv.id] = panel
                    yield panel
            with Vertical(id="detail-panel"):
                yield Static("Select a server", id="detail-header")
                yield ContainerTable(id="container-table")
        yield Footer()

    def on_mount(self) -> None:
        self._update_selection()
        table = self.query_one("#container-table", ContainerTable)
        table.add_columns(*COLUMNS)
        self.set_interval(self.cfg.refresh_interval, self._tick)
        self._tick()

    def _tick(self) -> None:
        # One worker per server; a server whose poll is still running is skipped,
        # never cancelled, so one slow or hung server cannot stall the others.
        for srv in self.cfg.servers:
            if srv.id not in self._inflight:
                self._inflight.add(srv.id)
                self.run_worker(self._poll_one(srv.id), group="poll")

    async def poll_now(self, force_inventory: bool = False) -> None:
        """Poll every server that is not already being polled, and wait for them."""
        ids = [s.id for s in self.cfg.servers if s.id not in self._inflight]
        self._inflight.update(ids)
        await asyncio.gather(*(self._poll_one(i, force_inventory) for i in ids))

    async def _poll_one(self, server_id: str, force_inventory: bool = False) -> None:
        self._inflight.add(server_id)
        try:
            now = time.monotonic()
            last = self._last_inventory.get(server_id)
            inventory = force_inventory or last is None or now - last >= self.cfg.inventory_interval
            if inventory:
                self._last_inventory[server_id] = now
            snap = await self.collector.poll_server(server_id, inventory)
        finally:
            self._inflight.discard(server_id)
        self._snaps[server_id] = snap
        panel = self._panels.get(server_id)
        if panel is not None:
            panel.update_data(snap)
        self._update_fleet_summary()
        if self.cfg.servers and self.cfg.servers[self.selected_index].id == server_id:
            self._update_detail()

    # navigation -----------------------------------------------------------
    def watch_selected_index(self, old: int, new: int) -> None:
        self._update_selection()
        self._update_detail()

    def _update_selection(self) -> None:
        for i, srv in enumerate(self.cfg.servers):
            panel = self._panels.get(srv.id)
            if panel is None:
                continue
            if i == self.selected_index:
                panel.add_class("selected")
            else:
                panel.remove_class("selected")

    def action_next_server(self) -> None:
        if self.cfg.servers:
            self.selected_index = (self.selected_index + 1) % len(self.cfg.servers)

    def action_prev_server(self) -> None:
        if self.cfg.servers:
            self.selected_index = (self.selected_index - 1) % len(self.cfg.servers)

    def action_open_server(self) -> None:
        if not self.cfg.servers:
            return
        srv = self.cfg.servers[self.selected_index]
        if srv.url:
            webbrowser.open(srv.url)
            self.notify(f"Opening {srv.url}")
        else:
            self.notify(f"No URL configured for {srv.id}", severity="warning")

    def action_refresh(self) -> None:
        self.run_worker(self.poll_now(force_inventory=True), group="poll")

    # rendering --------------------------------------------------------------
    def summary_text(self) -> str:
        snaps = list(self._snaps.values())
        total = len(self.cfg.servers)
        reachable = sum(1 for s in snaps if s.host is not None)
        down = total - reachable
        t = self.cfg.thresholds

        def avg(vals):
            vals = [v for v in vals if v is not None]
            return sum(vals) / len(vals) if vals else None

        def part(label, v, warn, crit):
            if v is None:
                return f"{label}: [dim]n/a[/dim]"
            c = severity_color(v, warn, crit)
            return f"{label}: [{c}]{v:.1f}%[/{c}]"

        hosts = [s.host for s in snaps if s.host is not None]
        text = f"Fleet: [bold green]{reachable}[/bold green]/{total} reachable"
        if down:
            text += f"  [bold red]{down} offline[/bold red]"
        text += ("  |  " + part("CPU", avg(h.cpu_percent for h in hosts), t["cpu_warn"], t["cpu_crit"])
                 + "  " + part("MEM", avg(h.mem_percent for h in hosts), t["mem_warn"], t["mem_crit"])
                 + "  " + part("DSK", avg(h.disk_root_percent for h in hosts), t["disk_warn"], t["disk_crit"])
                 + f"  |  {sum(len(s.containers) for s in snaps)} containers"
                 + f"  |  {datetime.now().strftime('%H:%M:%S')}")
        return text

    def _update_fleet_summary(self) -> None:
        self.query_one("#fleet-summary", FleetSummary).fleet_text = self.summary_text()

    def _update_detail(self) -> None:
        if not self.cfg.servers:
            return
        srv = self.cfg.servers[self.selected_index]
        s = self._snaps.get(srv.id)
        header = self.query_one("#detail-header", Static)
        table = self.query_one("#container-table", ContainerTable)
        table.clear()
        domain = f" [cyan]{escape(srv.domain)}[/cyan]" if srv.domain else ""
        if s is None:
            header.update(f"[bold]{srv.id}[/bold] ({srv.ip}){domain} - loading...")
            return
        status = "[red]OFFLINE[/red]" if s.host is None else (
            "[yellow]metrics off[/yellow]" if _metrics_off(s) else "[green]online[/green]")
        inv = s.inventory_at.astimezone().strftime("%H:%M:%S") if s.inventory_at else "-"
        header.update(
            f"[bold]{srv.id}[/bold] ({srv.ip}){domain} - {escape(srv.provider)} / {escape(srv.role)} - "
            f"{status}  sentinel {escape(s.version or '?')} ({srv.sentinel_container})\n"
            f"{len(s.stacks)} stacks, {len(s.containers)} containers, inventory {inv}"
            + (f"  [red]{escape(s.error[:60])}[/red]" if s.error else "")
        )
        for st in s.stacks:
            stack_label = st.resource or st.key
            domain_cell = ""
            if st.domains:
                domain_cell = st.domains[0] + (f" +{len(st.domains) - 1}" if len(st.domains) > 1 else "")
            for c in sorted(st.containers, key=lambda c: c.name):
                m = s.container_metrics.get(display_name(c))
                cpu = f"{m.cpu_percent:.1f}" if m and m.cpu_percent is not None else ""
                mem = fmt_bytes(m.mem_used) if m and m.mem_used is not None else ""
                image = c.image if len(c.image) <= 40 else c.image[:37] + "..."
                state = Text(c.state + (f" ({c.restart_count})" if c.state == "restarting" else ""),
                             style=STATE_STYLES.get(c.state, ""))
                health = Text(c.health or "-", style=HEALTH_STYLES.get(c.health or "", "dim"))
                table.add_row(
                    Text(c.name), Text(st.project or ("platform" if st.platform else "-")),
                    Text(stack_label, style="dim" if st.platform else ""), state, health,
                    cpu, mem, domain_cell, image,
                )

    async def on_unmount(self) -> None:
        await self.collector.close()


def run_tui(cfg: FleetConfig) -> int:
    from .collector import FleetCollector

    SentinelDashboard(cfg, FleetCollector(cfg)).run()
    return 0
