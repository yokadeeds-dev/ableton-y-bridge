# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""What a handler gets to work with: checked access to the Live Set.

Every handler receives a `LiveCtx` as its first argument. The lookups here
raise `CommandError` with a clear message instead of letting an IndexError
or a Live RuntimeError reach the client.
"""

from . import journal, settings
from .errors import (
    NOT_FOUND,
    UNSUPPORTED,
    WRONG_KIND,
    CommandError,
    out_of_range,
)
from .registry import DESTRUCTIVE, READ

NEEDS_CONFIRMATION = "needs_confirmation"

_NOTHING = object()


def peek(obj, attribute, fallback=None):
    """Read an attribute that Live may refuse for this kind of object."""
    try:
        return getattr(obj, attribute)
    except Exception:
        return fallback


def pick(sequence, index, what):
    """Bounds-checked indexing of a Live vector."""
    count = len(sequence)
    if index < 0 or index >= count:
        raise out_of_range(what, index, count)
    return sequence[index]


def track_kind(track):
    if peek(track, "is_foldable", False):
        return "group"
    if peek(track, "has_midi_input", False):
        return "midi"
    if peek(track, "has_audio_input", False):
        return "audio"
    return "other"


def parse_db(text):
    """'-6.0 dB' -> -6.0, '-inf dB' -> -inf."""
    token = str(text).lower().replace("db", "").strip().replace(",", ".")
    if "inf" in token:
        return float("-inf")
    return float(token)


def db_of(parameter, value=_NOTHING):
    """Display value of a volume-like parameter in dB."""
    if value is _NOTHING:
        value = parameter.value
    return parse_db(parameter.str_for_value(value))


def value_for_db(parameter, target_db):
    """Find the raw parameter value whose display reads ``target_db``.

    Live does not expose its fader law, so the display string is searched by
    bisection. The result is exact to the 0.1 dB the display resolves.
    """
    low, high = float(parameter.min), float(parameter.max)
    try:
        if target_db <= db_of(parameter, low):
            return low
        if target_db >= db_of(parameter, high):
            return high
        for _ in range(36):
            middle = (low + high) / 2.0
            if db_of(parameter, middle) < target_db:
                low = middle
            else:
                high = middle
        return high
    except (ValueError, AttributeError, RuntimeError):
        # No readable display: use the documented law of Live's track fader
        # above -18 dB (0.85 = 0 dB, 0.025 per dB) and clamp below.
        return max(low, min(high, 0.85 + target_db / 40.0))


def same(left, right):
    """Equality that forgives float noise (Live stores 32-bit floats)."""
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left) - float(right)) <= 1e-5 * max(1.0, abs(float(left)))
        except (TypeError, ValueError):
            return False
    return left == right


def still_there(obj, collection):
    """Index of a Live object in a Live vector, or -1 if it is gone."""
    try:
        for index, candidate in enumerate(collection):
            if candidate == obj:
                return index
    except Exception:
        pass
    return -1


class LiveCtx(object):
    def __init__(self, surface, hub, request=None):
        self.surface = surface
        self.hub = hub
        self.song = surface.song()
        self.app = surface.application()
        self.confirmed = bool((request or {}).get("confirm"))
        self._records = []
        self._quiet = False
        journal.prepare(hub, self.song)

    # -- safety and journal ------------------------------------------------

    @staticmethod
    def admit(spec, request):
        """Called by the hub before a command runs; raises to refuse it."""
        if (spec.zone == DESTRUCTIVE and settings.confirm_required()
                and not (request or {}).get("confirm")):
            raise CommandError(
                NEEDS_CONFIRMATION,
                "'%s' is destructive (%s). Send it again with \"confirm\": true "
                "next to type and params once the user has agreed."
                % (spec.name, spec.summary),
            )

    def require_confirmation(self, what):
        """Same check for destructive work reached through another command."""
        if settings.confirm_required() and not self.confirmed:
            raise CommandError(
                NEEDS_CONFIRMATION,
                "%s is destructive. Send the request again with \"confirm\": true "
                "once the user has agreed." % what,
            )

    def quiet(self):
        """This call turned out to change nothing: no automatic journal entry."""
        self._quiet = True

    def record(self, text, undo=None, valid=None, kind=None):
        """Note a change for the journal.

        ``undo`` restores the previous state (it may return a `Later`),
        ``valid`` returns a reason text if the Set no longer looks the way
        this command left it, else None.
        """
        self._records.append((text, undo, valid, kind))

    def record_value(self, text, target, attribute, old, new=_NOTHING, label=None):
        """Journal a plain attribute change that is undone by writing ``old`` back."""
        if new is _NOTHING:
            new = getattr(target, attribute)
        name = label or attribute

        def valid():
            try:
                current = getattr(target, attribute)
            except Exception:
                return "the object no longer exists"
            if not same(current, new):
                return "%s was changed since (now %s)" % (name, current)
            return None

        def undo():
            setattr(target, attribute, old)
            return {"restored": name}

        self.record(text, undo, valid)

    def finish(self, spec, arguments, result):
        """Called by the hub after success: turn the notes into journal entries."""
        if not getattr(spec, "journal", True):
            return result
        records = self._records
        if not records:
            if spec.zone == READ or self._quiet:
                return result
            kind = journal.LIVE_UNDO if spec.undo == "live" else journal.NONE
            records = [("%s %s" % (spec.summary, journal.compact(arguments)), None, None, kind)]
        entries = [journal.add(self.hub, spec.name, arguments, text, undo, valid, kind)
                   for text, undo, valid, kind in records]
        if isinstance(result, dict):
            result = dict(result)
            result["journal"] = entries
        return result

    # -- general -----------------------------------------------------------

    @property
    def state(self):
        return self.hub.state

    @property
    def browser(self):
        browser = peek(self.app, "browser")
        if browser is None:
            raise CommandError(UNSUPPORTED, "Live's browser is not available right now")
        return browser

    def log(self, text):
        self.surface.log_message("[bridge] " + str(text))

    def live_module(self):
        """The `Live` API module (importable only inside Live)."""
        import Live

        return Live

    # -- tracks ------------------------------------------------------------

    def track(self, index):
        return pick(self.song.tracks, index, "track")

    def return_track(self, index):
        return pick(self.song.return_tracks, index, "return track")

    def strip(self, track_index=0, use_master=False, use_return=False, return_index=0):
        """Resolve the track/return/master addressing used by device tools.

        Returns ``(track, label)``.
        """
        if use_master:
            return self.song.master_track, "Master"
        if use_return:
            chosen = self.return_track(return_index)
            return chosen, chosen.name
        chosen = self.track(track_index)
        return chosen, chosen.name

    def device(self, strip, device_index):
        return pick(strip.devices, device_index, "device")

    def scene(self, index):
        return pick(self.song.scenes, index, "scene")

    # -- clips -------------------------------------------------------------

    def slot(self, track_index, slot_index):
        return pick(self.track(track_index).clip_slots, slot_index, "clip slot")

    def session_clip(self, track_index, slot_index, kind=None):
        """Clip in a Session slot. ``kind`` may be 'midi' or 'audio'."""
        slot = self.slot(track_index, slot_index)
        if not slot.has_clip:
            raise CommandError(
                NOT_FOUND,
                "clip slot %d on track %d is empty" % (slot_index, track_index),
            )
        clip = slot.clip
        self._require_kind(clip, kind)
        return clip

    def arrangement_clips(self, track_index):
        track = self.track(track_index)
        clips = peek(track, "arrangement_clips")
        if clips is None:
            raise CommandError(
                UNSUPPORTED, "this Live version does not expose arrangement clips"
            )
        return list(clips)

    def arrangement_clip(self, track_index, clip_index, kind=None):
        clip = pick(self.arrangement_clips(track_index), clip_index, "arrangement clip")
        self._require_kind(clip, kind)
        return clip

    def any_clip(self, track_index, clip_index, arrangement, kind=None):
        if arrangement:
            return self.arrangement_clip(track_index, clip_index, kind)
        return self.session_clip(track_index, clip_index, kind)

    @staticmethod
    def _require_kind(clip, kind):
        if kind == "midi" and not peek(clip, "is_midi_clip", False):
            raise CommandError(WRONG_KIND, "'%s' is not a MIDI clip" % clip.name)
        if kind == "audio" and not peek(clip, "is_audio_clip", False):
            raise CommandError(WRONG_KIND, "'%s' is not an audio clip" % clip.name)
