import threading
from unittest.mock import Mock

import pytest

from src.bot.dispatch import CeleryCommandDispatcher


async def test_dispatch_publishes_existing_tasks_off_event_loop():
    collection, digest = Mock(), Mock()
    threads = []
    collection.delay.side_effect = lambda: threads.append(threading.get_ident())
    dispatcher = CeleryCommandDispatcher(collection, digest)
    await dispatcher.collect()
    await dispatcher.digest(17)
    collection.delay.assert_called_once_with()
    digest.delay.assert_called_once_with(17, run_now=True)
    digest.delay.return_value.get.assert_not_called()
    assert threads[0] != threading.get_ident()


async def test_publish_error_reaches_command_handler():
    collection, digest = Mock(), Mock()
    collection.delay.side_effect = RuntimeError("broker unavailable")
    with pytest.raises(RuntimeError):
        await CeleryCommandDispatcher(collection, digest).collect()
