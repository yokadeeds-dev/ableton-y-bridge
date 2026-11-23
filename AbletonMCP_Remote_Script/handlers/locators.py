"""Arrangement locators (cue points).

Live's API can only toggle a locator at the current song position
(`set_or_delete_cue`) and rename one; a locator's time is read-only. On top
of that Live applies a new song position only after the current display
tick. Creating or deleting a locator is therefore a little sequence: move
the play position, wait a tick, toggle, wait a tick, check. The handlers
are written as generators that `stepwise` runs one step per tick.

Toggling follows the playhead while the song plays, so single-locator
commands refuse to run during playback; the bulk commands stop it.
"""

from ..errors import BAD_PARAMS, BUSY, CommandError, out_of_range
from ..registry import DESTRUCTIVE, READ, REVERSIBLE, Float, Int, Items, Later, Text, command

_SAME_SPOT = 0.01  # beats


def stepwise(steps):
    """Run a generator across display ticks; its return value is the result.

    Every ``yield`` in ``steps`` means "let Live catch up for one tick".
    """
    def advance():
        try:
            next(steps)
        except StopIteration as finished:
            return finished.value
        return Later(advance)

    return advance()


def _rows(song):
    cues = sorted(song.cue_points, key=lambda cue: cue.time)
    return [{"index": i, "name": cue.name, "time": cue.time} for i, cue in enumerate(cues)]


def _cue_at(song, time):
    for cue in song.cue_points:
        if abs(cue.time - time) < _SAME_SPOT:
            return cue
    return None


def _park(song, may_stop):
    """Stop what disturbs cue toggling; returns what `_unpark` needs."""
    state = {"playing": bool(song.is_playing), "looping": bool(song.loop),
             "position": song.current_song_time}
    if state["playing"]:
        if not may_stop:
            raise CommandError(BUSY, "stop playback first: locators can only be created "
                                     "or deleted while the transport is stopped")
        song.stop_playing()
    if state["looping"]:
        song.loop = False
    return state


def _unpark(song, state):
    if state["looping"]:
        song.loop = True
    song.current_song_time = state["position"]


def _toggle(song, time):
    """Generator: toggle the locator at ``time`` (two ticks)."""
    song.current_song_time = time
    yield
    song.set_or_delete_cue()
    yield


def _create_steps(song, time, name):
    """Generator: make sure a locator with ``name`` sits at ``time``."""
    created = False
    if _cue_at(song, time) is None:
        state = _park(song, may_stop=False)
        yield
        yield from _toggle(song, time)
        created = _cue_at(song, time) is not None
        _unpark(song, state)
        if not created:
            raise CommandError(BUSY, "Live did not create a locator at beat %s" % time)
    cue = _cue_at(song, time)
    if name:
        cue.name = name
    return created


def _delete_steps(song, time):
    """Generator: remove the locator at ``time``."""
    state = _park(song, may_stop=False)
    yield
    yield from _toggle(song, time)
    still_there = _cue_at(song, time) is not None
    _unpark(song, state)
    if still_there:
        raise CommandError(BUSY, "Live did not delete the locator at beat %s" % time)


def _remove_times(song, times):
    """Generator: delete the locators at ``times``; returns how many went."""
    deleted = 0
    for time in sorted(times, reverse=True):
        before = len(song.cue_points)
        yield from _toggle(song, time)
        after = len(song.cue_points)
        if after < before:
            deleted += 1
        elif after > before:
            # The toggle created one instead of deleting: take it back, stop.
            song.set_or_delete_cue()
            yield
            break
    return deleted


def _rebuild_steps(song, wanted):
    """Generator: make the locators equal to ``wanted`` [(time, name), ...]."""
    def is_wanted(time):
        return any(abs(time - target) < _SAME_SPOT for target, _name in wanted)

    created = renamed = 0
    state = _park(song, may_stop=True)
    yield
    for time in sorted((t for t, _n in wanted), reverse=True):
        if _cue_at(song, time) is None:
            yield from _toggle(song, time)
            created += 1 if _cue_at(song, time) is not None else 0
    surplus = [cue.time for cue in song.cue_points if not is_wanted(cue.time)]
    deleted = yield from _remove_times(song, surplus)
    _unpark(song, state)
    for time, name in wanted:
        cue = _cue_at(song, time)
        if cue is not None and name and cue.name != name:
            cue.name = name
            renamed += 1
    return {"created": created, "deleted": deleted, "renamed": renamed,
            "locators": _rows(song), "was_playing": state["playing"]}


def _record_restore(live, song, before, text):
    """Journal a bulk change; undo rebuilds the locators that were there before."""
    wanted = [(row["time"], row["name"]) for row in before]
    live.record(text, lambda: stepwise(_rebuild_steps(song, wanted)))


@command("get_locators", zone=READ, summary="All locators, ordered by time")
def get_locators(live):
    return {"locators": _rows(live.song)}


@command("create_locator", zone=REVERSIBLE,
         summary="Create a locator at a beat position (transport must be stopped)",
         params=[Float("time", None), Text("name", "")], timeout=20.0)
def create_locator(live, time, name):
    song = live.song
    if time is None:
        time = song.current_song_time
    if time < 0:
        raise CommandError(BAD_PARAMS, "time must not be negative")
    existing = _cue_at(song, time)
    name_before = existing.name if existing is not None else None

    def steps():
        created = yield from _create_steps(song, time, name)
        cue = _cue_at(song, time)
        if created:
            live.record(
                "Created locator '%s' at beat %g" % (cue.name, time),
                lambda: stepwise(_delete_steps(song, time)),
                lambda: None if _cue_at(song, time) is not None else "the locator is gone",
            )
        elif name and name != name_before:
            live.record_value("Locator at beat %g: '%s' -> '%s'" % (time, name_before, name),
                              cue, "name", name_before)
        else:
            live.quiet()
        return {"created": created, "time": cue.time, "name": cue.name,
                "count": len(song.cue_points)}

    return stepwise(steps())


@command("delete_locator", zone=REVERSIBLE,
         summary="Delete one locator by its index in time order",
         params=[Int("index")], timeout=20.0)
def delete_locator(live, index):
    song = live.song
    cues = sorted(song.cue_points, key=lambda cue: cue.time)
    if index < 0 or index >= len(cues):
        raise out_of_range("locator", index, len(cues))
    gone = {"name": cues[index].name, "time": cues[index].time}

    def steps():
        yield from _delete_steps(song, gone["time"])
        live.record(
            "Deleted locator '%s' at beat %g" % (gone["name"], gone["time"]),
            lambda: stepwise(_create_steps(song, gone["time"], gone["name"])),
            lambda: None if _cue_at(song, gone["time"]) is None
            else "there is a locator at that position again",
        )
        return {"deleted": gone, "remaining": len(song.cue_points)}

    return stepwise(steps())


@command("clear_locators", zone=DESTRUCTIVE, undo="live", timeout=120.0,
         summary="Delete all locators (stops playback while it works)")
def clear_locators(live):
    song = live.song
    before = _rows(song)

    def steps():
        state = _park(song, may_stop=True)
        yield
        deleted = yield from _remove_times(song, [cue.time for cue in song.cue_points])
        _unpark(song, state)
        if deleted:
            _record_restore(live, song, before, "Deleted all %d locators" % deleted)
        else:
            live.quiet()
        return {"deleted": deleted, "remaining": len(song.cue_points),
                "was_playing": state["playing"]}

    return stepwise(steps())


@command("rebuild_locators", zone=DESTRUCTIVE, undo="live", timeout=180.0,
         summary="Make the locators match a list of {time, name} (stops playback)",
         params=[Items("targets")])
def rebuild_locators(live, targets):
    try:
        wanted = [(float(t["time"]), str(t.get("name", ""))) for t in targets]
    except (KeyError, TypeError, ValueError):
        raise CommandError(BAD_PARAMS, "each target needs a numeric 'time'")
    song = live.song
    before = _rows(song)

    def steps():
        result = yield from _rebuild_steps(song, wanted)
        _record_restore(live, song, before, "Rebuilt the locators: %d created, %d deleted, "
                        "%d renamed" % (result["created"], result["deleted"], result["renamed"]))
        return result

    return stepwise(steps())
