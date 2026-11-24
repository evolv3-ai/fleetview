import asyncio

from rich.text import Text

from fleetview.collector import ServerCollector
from fleetview.models import ContainerInfo, FleetConfig
from fleetview.tui import ContainerTable, ServerPanel, SentinelDashboard

from .fakes import FakeRunner, fixture_responses, server

COLUMNS = ["Name", "Project", "Stack", "State", "Health", "CPU%", "MEM", "Domain", "Image"]


async def _snap(sid, summary="summary_full.json", containers="containers_current_full.json",
                inspect="inspect_htz04.jsonl"):
    fake = FakeRunner(fixture_responses(summary=summary, containers=containers, inspect=inspect))
    return await ServerCollector(server(sid), runner_factory=lambda s: fake).poll(True)


class FakeCollector:
    def __init__(self, builder):
        self.builder = builder
        self.polls = []
        self.closed = False

    async def poll(self, include_inventory):
        self.polls.append(include_inventory)
        return await self.builder()

    async def close(self):
        self.closed = True


def _cfg():
    return FleetConfig(servers=[server("htz-04-5-213"), server("htz-03-178-51")])


async def _two():
    a = await _snap("htz-04-5-213")
    b = await _snap("htz-03-178-51", summary="summary_metrics_off.json",
                    containers="containers_current_metrics_off.json", inspect="inspect_htz03.jsonl")
    return [a, b]


def _table_cells(table):
    return [[table.get_cell_at((r, c)) for c in range(len(table.columns))] for r in range(table.row_count)]


def _run(coro):
    return asyncio.run(coro)


def test_tui_container_table_columns():
    async def go():
        col = FakeCollector(_two)
        app = SentinelDashboard(_cfg(), col)
        async with app.run_test() as pilot:
            await app.poll_now()
            await pilot.pause()
            table = app.query_one("#container-table", ContainerTable)
            labels = [str(c.label) for c in table.columns.values()]
            assert labels == COLUMNS
            assert table.row_count == 19
            await pilot.press("j")
            await pilot.pause()
            assert table.row_count == 55
        assert col.closed
    _run(go())


def test_tui_rows_platform_last_and_metrics_joined():
    async def go():
        app = SentinelDashboard(_cfg(), FakeCollector(_two))
        async with app.run_test() as pilot:
            await app.poll_now()
            await pilot.pause()
            rows = _table_cells(app.query_one("#container-table", ContainerTable))
            names = [str(r[0]) for r in rows]
            assert names.index("coolify-proxy") > names.index("open-webui-jmpfdqus48z0jkidkogfcbm3")
            proxy = rows[names.index("coolify-proxy")]
            assert str(proxy[5]) == "12.5"
    _run(go())


def test_tui_renders_metrics_off():
    async def go():
        app = SentinelDashboard(_cfg(), FakeCollector(_two))
        async with app.run_test() as pilot:
            await app.poll_now()
            await pilot.pause()
            panel = app.query_one("#panel-htz-03-178-51", ServerPanel)
            text = str(panel.render())
            assert "metrics off" in text
            assert "OFFLINE" not in text
            assert "DSK" in text
    _run(go())


def test_tui_highlights_exited_and_restarting():
    async def build():
        s = await _snap("htz-04-5-213")
        base = dict(image="img", health=None, restart_count=3, labels={}, started_at=None)
        s.containers = [ContainerInfo(id="1", name="dead-one", state="exited", **base),
                        ContainerInfo(id="2", name="loopy", state="restarting", **base),
                        ContainerInfo(id="3", name="fine", state="running", **base)]
        from fleetview.grouping import group_stacks
        s.stacks = group_stacks(s.containers)
        return [s, s]

    async def go():
        app = SentinelDashboard(_cfg(), FakeCollector(build))
        async with app.run_test() as pilot:
            await app.poll_now()
            await pilot.pause()
            rows = _table_cells(app.query_one("#container-table", ContainerTable))
            by_name = {str(r[0]): r for r in rows}
            ex, rs, ok = by_name["dead-one"][3], by_name["loopy"][3], by_name["fine"][3]
            assert isinstance(ex, Text) and "red" in str(ex.style)
            assert isinstance(rs, Text) and "yellow" in str(rs.style)
            assert "red" not in str(getattr(ok, "style", "")) and "yellow" not in str(getattr(ok, "style", ""))
    _run(go())


def test_tui_server_panel_shows_load():
    async def go():
        app = SentinelDashboard(_cfg(), FakeCollector(_two))
        async with app.run_test() as pilot:
            await app.poll_now()
            await pilot.pause()
            text = str(app.query_one("#panel-htz-04-5-213", ServerPanel).render())
            assert "load 0.42 0.36 0.30" in text
            assert "CPU" in text and "MEM" in text
    _run(go())


def test_tui_fleet_summary_skips_none():
    async def go():
        app = SentinelDashboard(_cfg(), FakeCollector(_two))
        async with app.run_test() as pilot:
            await app.poll_now()
            await pilot.pause()
            text = app.summary_text()
            assert "CPU: [green]23.5%" in text  # only htz-04 has CPU; htz-03 is metrics-off
    _run(go())


def test_tui_inventory_interval():
    async def go():
        col = FakeCollector(_two)
        app = SentinelDashboard(_cfg(), col)
        async with app.run_test() as pilot:
            await app.poll_now()
            await app.poll_now()
            await pilot.pause()
        assert col.polls[0] is True
        assert col.polls[1] is False
    _run(go())
