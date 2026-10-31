"""
Tests that a track's file path from the Subsonic server reaches the library and stays current.

The server reports a path for every song, but the parser dropped it, so nothing could show
which file a track plays from. It is now kept as the mapping's details, and a library sync
rewrites a mapping whose details changed (a moved or retagged file), since existing tracks
would otherwise keep the details of the sync that first added them.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from libopensonic.media import Child
from music_assistant_models.media_items import ProviderMapping

from music_assistant.controllers.music.media.tracks import TracksController
from music_assistant.models.music_provider import MusicProvider
from music_assistant.providers.opensubsonic.parsers import parse_track

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "tracks" / "navi-various.track.json"
INSTANCE_ID = "opensubsonic--x"


def _mapping(details: str | None) -> ProviderMapping:
    return ProviderMapping(
        item_id="song_1",
        provider_domain="opensubsonic",
        provider_instance=INSTANCE_ID,
        in_library=True,
        details=details,
    )


def _mappings_match(library_details: str | None, provider_details: str | None) -> bool:
    """Run the sync's mapping check for a library and a provider mapping of the same song."""
    provider = SimpleNamespace(
        instance_id=INSTANCE_ID, is_streaming_provider=False, mass=MagicMock()
    )
    library_item = SimpleNamespace(provider_mappings={_mapping(library_details)})
    provider_item = SimpleNamespace(item_id="song_1", provider_mappings={_mapping(provider_details)})
    return MusicProvider._check_provider_mappings(
        cast("Any", provider), cast("Any", library_item), cast("Any", provider_item), True
    )


def test_parse_track_keeps_the_reported_path() -> None:
    """The song's path becomes the details of its provider mapping."""
    song = Child.from_json(FIXTURE.read_text(encoding="utf-8"))

    track = parse_track(MagicMock(), INSTANCE_ID, song)

    (mapping,) = track.provider_mappings
    assert mapping.details == song.path
    assert mapping.details


def test_a_changed_path_makes_the_sync_update_the_mapping() -> None:
    """Different details on the provider side count as a changed mapping."""
    assert not _mappings_match("Old/01 - Song.mp3", "New/01 - Song.mp3")
    assert not _mappings_match(None, "New/01 - Song.mp3")


def test_unchanged_or_unreported_details_leave_the_mapping_alone() -> None:
    """Equal details, or none from the provider, do not trigger an update."""
    assert _mappings_match("Same/01 - Song.mp3", "Same/01 - Song.mp3")
    assert _mappings_match("Stored/01 - Song.mp3", None)


def test_sync_details_rows_carry_the_stored_details() -> None:
    """The sync's lightweight snapshot reads the stored details, so the check above can see them."""
    ctrl = TracksController.__new__(TracksController)
    row = {
        "provider_mappings": json.dumps(
            [
                {
                    "item_id": "song_1",
                    "provider_domain": "opensubsonic",
                    "provider_instance": INSTANCE_ID,
                    "available": 1,
                    "in_library": 1,
                    "is_unique": None,
                    "details": "Stored/01 - Song.mp3",
                }
            ]
        )
    }

    (mapping,) = ctrl._parse_sync_details_mappings(row)

    assert mapping.details == "Stored/01 - Song.mp3"
