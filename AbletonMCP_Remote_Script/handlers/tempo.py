"""Tempo follower: steps the song tempo through a list of breakpoints.

A stopgap for Sets without tempo automation: while it is active the bridge
watches the play position ten times a second and sets the song tempo to the
value of the last breakpoint passed. For sample-accurate tempo changes write
real automation into the .als file (MCP tool ``set_tempo_automation``).
"""

from ..errors import BAD_PARAMS, CommandError
from ..registry import READ, REVERSIBLE, Items, command

_KEY = "tempo_follow"


def follow_tick(live):
    """Called from the hub's tick while a tempo map is active."""
    plan = live.state.get(_KEY)
    if not plan:
        live.state.get("tickers", {}).pop(_KEY, None)
        return
    position = live.song.current_song_time
    current = 0
    for index, point in enumerate(plan["points"]):
        if position >= point["beat"]:
            current = index
        else:
            break
    if current != plan["at"]:
        plan["at"] = current
        live.song.tempo = plan["points"][current]["bpm"]


@command("set_tempo_follow", zone=REVERSIBLE, undo="none",
         summary="Follow a tempo map [{beat, bpm}] during playback; [] switches it off",
         params=[Items("breakpoints", [])])
def set_tempo_follow(live, breakpoints):
    points = []
    for entry in breakpoints:
        try:
            beat, bpm = float(entry["beat"]), float(entry["bpm"])
        except (KeyError, TypeError, ValueError):
            raise CommandError(BAD_PARAMS, "each breakpoint needs numeric 'beat' and 'bpm'")
        if not 20.0 <= bpm <= 999.0:
            raise CommandError(BAD_PARAMS, "bpm %s is outside 20..999" % bpm)
        points.append({"beat": beat, "bpm": bpm})
    points.sort(key=lambda point: point["beat"])
    tickers = live.state.setdefault("tickers", {})
    if not points:
        live.state.pop(_KEY, None)
        tickers.pop(_KEY, None)
        return {"active": False, "points": 0}
    live.state[_KEY] = {"points": points, "at": -1}
    tickers[_KEY] = ("handlers.tempo", "follow_tick")
    return {"active": True, "points": len(points),
            "first_bpm": points[0]["bpm"], "last_beat": points[-1]["beat"]}


@command("get_tempo_follow", zone=READ, summary="State of the tempo follower")
def get_tempo_follow(live):
    plan = live.state.get(_KEY)
    if not plan:
        return {"active": False, "points": []}
    return {"active": True, "points": plan["points"], "current_index": plan["at"]}
