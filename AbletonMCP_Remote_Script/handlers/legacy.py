"""Old keyword calls that used to ride on ``set_warp_markers_batch``.

Before the bridge had a command register, extra functions were reached by
sending a word instead of a track number, for example
``set_warp_markers_batch(track_index="version")``. Notes, prompts and habits
still use these spellings, so they are mapped onto the real commands here.
New code should call the real commands.
"""

from ..errors import BAD_PARAMS, CommandError
from . import arrangement, clips, devices, locators, session, system, tempo, tracks, warp_intel

_WORDS = ("reload", "version", "save", "warp_intel", "tempo", "probe")
_PREFIXES = ("norm:", "del:")


def is_keyword(track_index):
    if not isinstance(track_index, str):
        return False
    word = track_index.strip()
    return word in _WORDS or word.startswith(_PREFIXES)


def _first(markers):
    return markers[0] if markers and isinstance(markers[0], dict) else {}


def route(live, word, clip_index, markers):
    word = word.strip()
    if word == "reload":
        live.quiet()
        return system.hot_reload(live)
    if word == "version":
        live.quiet()
        return system.get_version(live)
    if word == "save":
        return session.save_project(live)
    if word == "probe":
        live.quiet()
        return arrangement.probe_arrangement_api(live)
    if word == "warp_intel":
        return _warp_intel(live, clip_index, markers)
    if word.startswith("norm:"):
        track_index, clip_number = _two_numbers(word)
        options = _first(markers)
        return clips.normalize_clip(
            live, track_index, clip_number,
            bool(options.get("arrangement", True)),
            float(options.get("target_db", 0.0)),
            options.get("peak_db"),
        )
    if word.startswith("del:"):
        live.require_confirmation("Deleting a track")
        return tracks.delete_track(live, _one_number(word))
    if word == "tempo":
        return _tempo_payload(live, markers)
    raise CommandError(BAD_PARAMS, "unknown keyword '%s'" % word)


def _one_number(word):
    try:
        return int(word.split(":")[1])
    except (IndexError, ValueError):
        raise CommandError(BAD_PARAMS, "'%s' needs a number after the colon" % word)


def _two_numbers(word):
    parts = word.split(":")
    try:
        return int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        raise CommandError(BAD_PARAMS, "'%s' must look like norm:<track>:<clip>" % word)


def _warp_intel(live, clip_index, markers):
    # clip_index arrives as "track:clip", markers as a one-element list.
    parts = str(clip_index).split(":")
    try:
        track_index = int(parts[0])
        clip_number = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        raise CommandError(BAD_PARAMS, "clip_index must look like '<track>:<clip>'")
    if not markers:
        raise CommandError(BAD_PARAMS, "markers must hold one operation object")
    operation = markers[0] if isinstance(markers, list) else markers
    return warp_intel.run(live, track_index, clip_number, operation)


def _tempo_payload(live, markers):
    """The 'tempo' keyword carried either a tempo map or one of several jobs."""
    first = _first(markers)
    if "delete_track" in first:
        live.require_confirmation("Deleting a track")
        return tracks.delete_track(live, int(first["delete_track"]))
    if "arr_clip_batch" in first:
        return arrangement.create_arrangement_audio_clips(live, first["arr_clip_batch"])
    if "load_arr_audio" in first:
        return arrangement.create_arrangement_audio_clips(live, [first["load_arr_audio"]])
    if "fix_arr_warp" in first:
        return arrangement.repair_arrangement_warp(live, first["fix_arr_warp"])
    if "load_vst" in first:
        return devices.load_vst_plugin(live, str(first["load_vst"]), first.get("track", 0),
                                       str(first.get("type", "vst3")))
    if "probe_arr" in first:
        live.quiet()
        return arrangement.probe_arrangement_api(live)
    if "clear_locators" in first:
        live.require_confirmation("Clearing all locators")
        return locators.clear_locators(live)
    if "rebuild_locators" in first:
        live.require_confirmation("Rebuilding the locators")
        return locators.rebuild_locators(live, first["rebuild_locators"])
    return tempo.set_tempo_follow(live, markers)
