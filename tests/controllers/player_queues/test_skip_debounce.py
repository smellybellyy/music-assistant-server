"""
Tests that a next/previous press plays at once and only a burst of presses is debounced.

Every press used to wait out the full debounce window before the new item started, so a
single skip took a second plus the player's own start time. The first press of a burst now
plays at once; presses following it within SKIP_DEBOUNCE are still collected into one play.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from music_assistant_models.enums import PlaybackState
from music_assistant_models.player_queue import PlayerQueue
from music_assistant_models.queue_item import QueueItem

from music_assistant.controllers.player_queues import PlayerQueuesController
from music_assistant.controllers.player_queues import controller as controller_module
from music_assistant.controllers.player_queues.constants import SKIP_DEBOUNCE
from music_assistant.controllers.player_queues.state import PlayerQueueData

QUEUE_ID = "q1"


class _Clock:
    """A settable stand-in for time.monotonic."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Patch the controller's monotonic clock."""
    fake = _Clock()
    monkeypatch.setattr(controller_module.time, "monotonic", fake)
    return fake


def _controller() -> PlayerQueuesController:
    """Build a bare controller playing item 2 of five items."""
    ctrl = PlayerQueuesController.__new__(PlayerQueuesController)
    queue = PlayerQueue(queue_id=QUEUE_ID, active=True, display_name="Q1", available=True, items=5)
    items = [
        QueueItem(queue_id=QUEUE_ID, queue_item_id=str(i), name=str(i), duration=200)
        for i in range(5)
    ]
    queue.state = PlaybackState.PLAYING
    queue.current_index = 2
    queue.current_item = items[2]
    queue.elapsed_time = 1
    queue_data = PlayerQueueData(queue=queue)
    queue_data.items = items
    ctrl._queue_data = {QUEUE_ID: queue_data}
    ctrl.signal_update = Mock()  # type: ignore[method-assign]
    ctrl._check_player_permission = Mock()  # type: ignore[method-assign]
    ctrl._get_next_index = Mock(side_effect=lambda _q, idx, *_a, **_kw: idx + 1)  # type: ignore[method-assign]
    ctrl.mass = MagicMock()
    ctrl.mass.call_later = Mock()
    ctrl.logger = MagicMock()
    return ctrl


def _scheduled(ctrl: PlayerQueuesController) -> list[tuple[Any, int]]:
    """Return (delay, index) of every play_index the presses scheduled."""
    return [(c.args[0], c.args[3]) for c in ctrl.mass.call_later.call_args_list]


async def test_a_single_next_plays_at_once(clock: _Clock) -> None:
    """One press schedules play_index without delay, under the queue's debounce task id."""
    ctrl = _controller()

    await ctrl.next(QUEUE_ID)

    assert _scheduled(ctrl) == [(0, 3)]
    call = ctrl.mass.call_later.call_args
    assert call.args[1] == ctrl.play_index
    assert call.kwargs["task_id"] == f"queue_play_index_{QUEUE_ID}"


async def test_a_burst_of_next_presses_plays_its_last_item_after_the_window(clock: _Clock) -> None:
    """Presses inside the window replace the pending play and wait, counting on from each other."""
    ctrl = _controller()

    await ctrl.next(QUEUE_ID)
    clock.now += 0.3
    await ctrl.next(QUEUE_ID)
    clock.now += 0.3
    await ctrl.next(QUEUE_ID)

    assert _scheduled(ctrl) == [(0, 3), (SKIP_DEBOUNCE, 4), (SKIP_DEBOUNCE, 5)]


async def test_a_press_after_the_window_plays_at_once_again(clock: _Clock) -> None:
    """Once the window has passed, the next press starts a new burst and plays at once."""
    ctrl = _controller()

    await ctrl.next(QUEUE_ID)
    clock.now += SKIP_DEBOUNCE + 0.1
    await ctrl.next(QUEUE_ID)

    assert _scheduled(ctrl) == [(0, 3), (0, 4)]


async def test_previous_shares_the_debounce_with_next(clock: _Clock) -> None:
    """Previous plays at once on its own and joins a burst started by next."""
    ctrl = _controller()

    await ctrl.previous(QUEUE_ID)
    clock.now += SKIP_DEBOUNCE + 0.1
    await ctrl.next(QUEUE_ID)
    clock.now += 0.2
    await ctrl.previous(QUEUE_ID)

    assert _scheduled(ctrl) == [(0, 1), (0, 2), (SKIP_DEBOUNCE, 1)]
