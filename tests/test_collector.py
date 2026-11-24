import asyncio

from fleetview.collector import FleetCollector, ServerCollector, sentinel_commands
from fleetview.models import FleetConfig
from fleetview.transport import CommandResult, TransportError, remote_command

from .fakes import FakeRunner, fixture_responses, server


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def run(coro):
    return asyncio.run(coro)


def down():
    return {k: TransportError("down") for k in fixture_responses()}


def test_poll_builds_snapshot_from_fixtures():
    fake = FakeRunner(fixture_responses())
    col = ServerCollector(server(), runner_factory=lambda s: fake)
    snap = run(col.poll(True))
    assert snap.online
    assert snap.version == "1.1.5"
    assert snap.health == "ok"
    assert snap.stacks
    assert len(snap.containers) == 19
    assert snap.container_metrics["coolify-proxy"].cpu_percent == 12.5
    assert snap.error is None
    assert snap.fetched_at is not None and snap.fetched_at.tzinfo is not None
    assert snap.inventory_at is not None


def test_fleet_poll_isolates_failures():
    servers = [server("a-01", ip="1.1.1.1"), server("b-02", ip="2.2.2.2"), server("c-03", ip="3.3.3.3")]
    bad = {k: TransportError("auth failed") for k in fixture_responses()}

    def factory(s):
        return FakeRunner(bad if s.id == "b-02" else fixture_responses())

    fc = FleetCollector(FleetConfig(servers=servers), runner_factory=factory)
    snaps = run(fc.poll(True))
    assert [s.server.id for s in snaps] == ["a-01", "b-02", "c-03"]
    assert snaps[0].online and snaps[2].online
    assert not snaps[1].online
    assert "auth failed" in snaps[1].error


def test_fleet_poll_isolates_unexpected_exception():
    servers = [server("a-01"), server("b-02")]

    def factory(s):
        if s.id == "b-02":
            raise RuntimeError("boom")
        return FakeRunner(fixture_responses())

    snaps = run(FleetCollector(FleetConfig(servers=servers), runner_factory=factory).poll(True))
    assert snaps[0].online
    assert not snaps[1].online and "boom" in snaps[1].error


def test_reconnect_backoff():
    calls = []
    clock = Clock()

    def factory(s):
        calls.append(1)
        return FakeRunner(down())

    col = ServerCollector(server(), runner_factory=factory, clock=clock)
    first = run(col.poll(True))
    assert "down" in first.error
    assert len(calls) == 1
    clock.t += 3
    second = run(col.poll(True))
    assert len(calls) == 1
    assert second.error.startswith("reconnecting in")
    assert not second.online
    clock.t += 3  # 6 s after the failure: past the 5 s backoff
    run(col.poll(True))
    assert len(calls) == 2
    clock.t += 6  # second failure -> 10 s backoff
    assert run(col.poll(True)).error.startswith("reconnecting in")
    assert len(calls) == 2


def test_backoff_resets_on_success():
    clock = Clock()
    state = {"fail": True}

    def factory(s):
        return FakeRunner(down() if state["fail"] else fixture_responses())

    col = ServerCollector(server(), runner_factory=factory, clock=clock)
    run(col.poll(True))
    state["fail"] = False
    clock.t += 6
    assert run(col.poll(True)).online
    state["fail"] = True
    col._runner.responses = down()  # the live connection drops
    assert "down" in run(col.poll(True)).error
    clock.t += 6  # backoff restarted at 5 s, not 10 s
    assert not run(col.poll(True)).error.startswith("reconnecting in")


def test_inventory_kept_between_polls():
    fake = FakeRunner(fixture_responses())
    col = ServerCollector(server(), runner_factory=lambda s: fake)
    first = run(col.poll(True))
    fake.commands.clear()
    second = run(col.poll(False))
    assert not any("docker ps" in c for c in fake.commands)
    assert [s.key for s in second.stacks] == [s.key for s in first.stacks]
    assert second.inventory_at == first.inventory_at


def test_first_poll_fetches_inventory_even_if_not_requested():
    fake = FakeRunner(fixture_responses())
    snap = run(ServerCollector(server(), runner_factory=lambda s: fake).poll(False))
    assert any("docker ps" in c for c in fake.commands)
    assert snap.stacks


def test_sudo_password_prompt_is_error():
    resp = {k: CommandResult(1, "", "sudo: a password is required\n") for k in fixture_responses()}
    fake = FakeRunner(resp)
    snap = run(ServerCollector(server(user="admin"), runner_factory=lambda s: fake).poll(True))
    assert snap.error == "sudo requires a password for admin"
    assert not snap.online
    assert fake.commands and all(c.startswith("sudo -n sh -c ") for c in fake.commands)


def test_remote_command_prefixes_sudo():
    assert remote_command(server(user="admin"), "docker ps") == "sudo -n sh -c 'docker ps'"
    assert remote_command(server(user="root"), "docker ps") == "docker ps"


def test_inspect_partial_output_kept():
    lines = [l for l in fixture_responses()["docker ps"].stdout.splitlines() if l.strip()][:2]
    resp = fixture_responses()
    resp["docker ps"] = CommandResult(1, "\n".join(lines) + "\n", "Error: No such object: abc")
    snap = run(ServerCollector(server(), runner_factory=lambda s: FakeRunner(resp)).poll(True))
    assert len(snap.containers) == 2
    assert "inventory partial" in snap.error


def test_command_timeout_is_error_not_crash():
    resp = fixture_responses()
    resp["/api/summary"] = asyncio.TimeoutError()
    snap = run(ServerCollector(server(), runner_factory=lambda s: FakeRunner(resp)).poll(True))
    assert not snap.online
    assert "summary" in snap.error and "timeout" in snap.error
    assert snap.containers  # inventory still collected


def test_error_truncated_to_200():
    resp = {k: CommandResult(2, "", "x" * 500) for k in fixture_responses()}
    snap = run(ServerCollector(server(), runner_factory=lambda s: FakeRunner(resp)).poll(True))
    assert len(snap.error) <= 200


def test_token_never_in_command():
    cmds = sentinel_commands("coolify-sentinel")
    assert set(cmds) == {"health", "version", "summary", "containers"}
    for name in ("summary", "containers"):
        c = cmds[name]
        assert "$TOKEN" in c
        assert "TOKEN=" not in c
        # the header goes to curl on stdin, so the token is never a curl argv element
        assert "-H @-" in c
        assert c.startswith("docker exec coolify-sentinel sh -c '")
    for name in ("health", "version"):
        assert "TOKEN" not in cmds[name]
    assert cmds["containers"].endswith("/api/containers/current'")


def test_harmless_sudo_warning_is_not_password_error():
    resp = fixture_responses()
    for k, v in list(resp.items()):
        resp[k] = CommandResult(v.exit_status, v.stdout, "sudo: unable to resolve host vmi123: Name or service not known\n")
    snap = run(ServerCollector(server(user="admin"), runner_factory=lambda s: FakeRunner(resp)).poll(True))
    assert snap.error is None
    assert snap.online


def test_all_commands_timing_out_starts_backoff():
    clock = Clock()
    calls = []

    def factory(s):
        calls.append(1)
        return FakeRunner({k: asyncio.TimeoutError() for k in fixture_responses()})

    col = ServerCollector(server(), runner_factory=factory, clock=clock)
    first = run(col.poll(True))
    assert not first.online and "timeout" in first.error
    clock.t += 2
    assert run(col.poll(True)).error.startswith("reconnecting in")
    assert len(calls) == 1


def test_hung_poll_is_capped_and_backs_off():
    class Hang(FakeRunner):
        async def run(self, cmd, timeout):
            await asyncio.sleep(30)

    clock = Clock()
    col = ServerCollector(server(), runner_factory=lambda s: Hang({}), clock=clock, poll_timeout=0.2)
    snap = run(asyncio.wait_for(col.poll(True), 5))
    assert not snap.online and "timeout" in snap.error
    assert run(col.poll(True)).error.startswith("reconnecting in")


def test_fleet_poll_server_by_id():
    servers = [server("a-01"), server("b-02")]
    fc = FleetCollector(FleetConfig(servers=servers), runner_factory=lambda s: FakeRunner(fixture_responses()))
    snap = run(fc.poll_server("b-02", True))
    assert snap.server.id == "b-02" and snap.online
