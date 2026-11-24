import asyncio

import pytest

from fleetview.transport import SSHRunner

from .fakes import server


class FakeProcess:
    def __init__(self, delay):
        self.delay = delay
        self.closed = False
        self.exit_status = 0

    async def communicate(self):
        await asyncio.sleep(self.delay)
        return "out", ""

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, delay):
        self.proc = FakeProcess(delay)

    async def create_process(self, cmd):
        return self.proc

    def close(self):
        pass


def test_timed_out_command_closes_channel():
    r = SSHRunner(server())
    r._conn = FakeConn(delay=5)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(r.run("docker ps", timeout=0.05))
    assert r._conn.proc.closed


def test_cancelled_command_closes_channel():
    r = SSHRunner(server())
    r._conn = FakeConn(delay=5)

    async def go():
        t = asyncio.create_task(r.run("docker ps", timeout=10))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(go())
    assert r._conn.proc.closed


def test_completed_command_returns_result():
    r = SSHRunner(server())
    r._conn = FakeConn(delay=0)
    res = asyncio.run(r.run("docker ps", timeout=1))
    assert (res.exit_status, res.stdout, res.stderr) == (0, "out", "")
