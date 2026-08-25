import signal

import pytest

from api.services.crawler_manager import CrawlerManager


@pytest.mark.asyncio
async def test_stop_terminates_process_group(monkeypatch):
    manager = CrawlerManager()

    class Process:
        pid = 123
        returncode = None
        stdout = None

        def poll(self):
            return self.returncode

        def wait(self):
            self.returncode = -signal.SIGTERM

    manager.process = Process()
    alive = iter([None, ProcessLookupError(), ProcessLookupError()])
    signals = []

    def killpg(pgid, sig):
        result = next(alive)
        if result:
            raise result
        signals.append((pgid, sig))

    monkeypatch.setattr("os.getpgid", lambda pid: pid)
    monkeypatch.setattr("os.killpg", killpg)
    monkeypatch.setattr("asyncio.sleep", lambda _: _noop())
    assert await manager.stop()
    assert signals == [(123, signal.SIGTERM)]


async def _noop():
    pass
