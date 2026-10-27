"""
Tests that skipping holds the queue on the new item while the player still reports the old one.

A skip while playing used to show the new item, jump back to the one playing before and then
forward again: the start wait in play_index is already satisfied by a player that is playing
(the old item), so the next player report - still naming the old item - moved the queue back.
A skip pressed while the previous press was still loading lost its place the same way, and the
next press counted on from the old item, so several skips in a row went nowhere.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock

from music_assistant_models.enums import PlaybackState
from music_assistant_models.player_queue import PlayerQueue
from music_assistant_models.queue_item import QueueItem

from music_assistant.controllers.player_queues import PlayerQueuesController
from music_assistant.controllers.player_queues.state import PlayerQueueData
from music_assistant.models.player import Player

QUEUE_ID = "q1"


def _controller() -> tuple[PlayerQueuesController, PlayerQueue]:
    """Build a bare controller playing item "a" of a, b, c."""
    ctrl = PlayerQueuesController.__new__(PlayerQueuesController)
    queue = PlayerQueue(queue_id=QUEUE_ID, active=True, display_name="Q1", available=True, items=3)
    items = [
        QueueItem(queue_id=QUEUE_ID, queue_item_id=item_id, name=item_id, duration=200)
        for item_id in ("a", "b", "c")
    ]
    queue.state = PlaybackState.PLAYING
    queue.current_index = 0
    queue.current_item = items[0]
    queue_data = PlayerQueueData(queue=queue)
    queue_data.items = items
    ctrl._queue_data = {QUEUE_ID: queue_data}
    ctrl.signal_update = Mock()  # type: ignore[method-assign]
    ctrl._check_player_permission = Mock()  # type: ignore[method-assign]
    ctrl._load_item = AsyncMock()  # type: ignore[method-assign]
    ctrl._get_next_index = Mock(side_effect=lambda _q, idx, *_a, **_kw: idx + 1)  # type: ignore[method-assign]
    ctrl.get_next_item = Mock(return_value=None)  # type: ignore[method-assign]
    ctrl.player_media_from_queue_item = AsyncMock()  # type: ignore[method-assign]
    ctrl.mass = MagicMock()
    ctrl.mass.players.play_media = AsyncMock()
    ctrl.logger = MagicMock()
    return ctrl, queue


def _player_reporting(item_id: str) -> Player:
    """Return a player that is playing and names item_id of the queue as its current media."""
    player = SimpleNamespace(
        player_id=QUEUE_ID,
        active_output_protocol="native",
        current_media=SimpleNamespace(source_id=QUEUE_ID, queue_item_id=item_id, uri=None),
        state=SimpleNamespace(playback_state=PlaybackState.PLAYING, corrected_elapsed_time=80.0),
    )
    return cast("Player", player)


def _current(queue: PlayerQueue) -> str | None:
    return queue.current_item.queue_item_id if queue.current_item else None


async def test_a_report_of_the_old_item_after_a_skip_keeps_the_new_item() -> None:
    """The player naming the item it played before the skip does not move the queue back."""
    ctrl, queue = _controller()

    await ctrl.play_index(QUEUE_ID, 1)
    ctrl._update_current_index_from_player(queue, _player_reporting("a"))

    assert queue.current_index == 1
    assert _current(queue) == "b"


async def test_the_player_reporting_the_new_item_ends_the_hold() -> None:
    """Once the player names the new item, its reports drive the queue again."""
    ctrl, queue = _controller()

    await ctrl.play_index(QUEUE_ID, 1)
    ctrl._update_current_index_from_player(queue, _player_reporting("b"))
    # a later track change reported by the player itself is followed as before
    ctrl._update_current_index_from_player(queue, _player_reporting("c"))

    assert ctrl._queue_data[QUEUE_ID].awaited_item_id is None
    assert _current(queue) == "c"


async def test_a_player_that_never_switches_is_followed_after_the_start_timeout() -> None:
    """The hold expires, so a failed switch cannot pin the queue to an item that is not playing."""
    ctrl, queue = _controller()

    await ctrl.play_index(QUEUE_ID, 1)
    ctrl._queue_data[QUEUE_ID].awaited_until = time.monotonic() - 1
    ctrl._update_current_index_from_player(queue, _player_reporting("a"))

    assert _current(queue) == "a"


async def test_the_next_skip_counts_on_from_the_new_item() -> None:
    """
    A press that waited for the previous play counts on from the item that play started.

    The press waits for the queue's lock while the previous one loads; a stale report in
    between used to put the queue back, and the press then counted on from the old item.
    """
    ctrl, queue = _controller()

    await ctrl.play_index(QUEUE_ID, 1)
    ctrl._update_current_index_from_player(queue, _player_reporting("a"))
    await ctrl.next(QUEUE_ID)

    assert _current(queue) == "c"
    call_later = cast("Mock", ctrl.mass.call_later)
    assert call_later.call_args.args[1:] == (ctrl.play_index, QUEUE_ID, 2)


async def test_a_play_ends_the_transition_and_awaits_its_item() -> None:
    """play_index still clears the transition, and holds the queue on the item it started."""
    ctrl, queue = _controller()

    await ctrl.play_index(QUEUE_ID, 2)

    queue_data = ctrl._queue_data[QUEUE_ID]
    assert queue_data.transitioning is False
    assert queue_data.awaited_item_id == "c"
    assert _current(queue) == "c"
