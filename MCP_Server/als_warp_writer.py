"""
ALS Warp Marker Writer
======================
Direct manipulation of Ableton Live .als project files to bypass the
main-thread deadlock of clip.set_warp_marker()/add_warp_marker().

Ableton .als files are GZIP-compressed XML. Warp markers are stored
per AudioClip under <WarpMarkers><WarpMarker Id="N" SecTime="..." BeatTime="..."/>

This module is file-I/O only — no Ableton API calls, no deadlock risk.
It can be used standalone (CLI) or imported as a library by server.py.

Usage workflow for the Drums-181-Marker problem:
    1. read_als("CP.als")
    2. get_clip_markers(tree, "[SUNO] Bass", "Concrete Pulse (Bass)") -> bass markers
    3. compute_offset_markers(bass_markers, offset=-1.2190)           -> drum markers
    4. set_clip_markers(tree, "[SUNO] Drums", "Concrete Pulse (Drums)", drum_markers)
    5. write_als(tree, "CP.als", backup=True)
    6. In Ableton: close/reopen project (or toggle warping on the clip)

Created: 2026-04-18
Author: yokadeeds-dev, with Claude
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET


# ── Types ───────────────────────────────────────────────────────────
Marker = Tuple[float, float]  # (sec_time, beat_time)


class ALSFormatError(Exception):
    """Raised when a file is not a valid Ableton .als (GZIP-XML)."""


class ALSClipNotFound(Exception):
    """Raised when the target track/clip cannot be located."""


# ── I/O ─────────────────────────────────────────────────────────────
def read_als(path: str | Path) -> ET.ElementTree:
    """
    Read and decompress a .als file, return an ElementTree.
    Raises ALSFormatError on any format issue.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"ALS file not found: {path}")
    try:
        with gzip.open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ALSFormatError(f"Not a valid GZIP file: {path} ({e})") from e
    try:
        tree = ET.ElementTree(ET.fromstring(raw))
    except ET.ParseError as e:
        raise ALSFormatError(f"Corrupt XML in {path}: {e}") from e
    root = tree.getroot()
    if root.tag != "Ableton":
        raise ALSFormatError(
            f"Root element is <{root.tag}>, expected <Ableton>. Is this really a .als file?"
        )
    return tree


def write_als(
    tree: ET.ElementTree,
    path: str | Path,
    backup: bool = True,
) -> Optional[Path]:
    """
    Write the ElementTree back to a .als file as GZIP-compressed XML.
    Creates a timestamped backup first if backup=True.
    Returns the backup path (or None if no backup was made).

    NOTE: If Ableton has this file open, Live may overwrite our changes when
    the user saves. The caller is responsible for warning about this.
    """
    path = Path(path)
    backup_path: Optional[Path] = None
    if backup and path.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_suffix(f".als.bak_{ts}")
        shutil.copy2(path, backup_path)

    # Serialize with XML declaration (Ableton uses standard XML header)
    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        tree.getroot(),
        encoding="utf-8",
        xml_declaration=False,
    )
    with gzip.open(path, "wb", compresslevel=6) as f:
        f.write(xml_bytes)
    return backup_path


# ── Clip/Marker Access ──────────────────────────────────────────────
def _clip_name(clip: ET.Element) -> str:
    el = clip.find("Name")
    return el.get("Value", "") if el is not None else ""


def _track_name(track: ET.Element) -> str:
    el = track.find(".//EffectiveName")
    return el.get("Value", "") if el is not None else ""


def find_clip(
    tree: ET.ElementTree,
    track_name: str,
    clip_name: Optional[str] = None,
    clip_index: Optional[int] = None,
) -> ET.Element:
    """
    Locate an AudioClip by track name and either clip name or clip index
    (into that track's arrangement clips).
    Raises ALSClipNotFound if no match.
    """
    root = tree.getroot()
    for track in root.findall(".//AudioTrack"):
        if _track_name(track) != track_name:
            continue
        arr_clips = track.findall(".//ArrangerAutomation//AudioClip")
        if clip_index is not None:
            if 0 <= clip_index < len(arr_clips):
                return arr_clips[clip_index]
            raise ALSClipNotFound(
                f"Track '{track_name}' has {len(arr_clips)} clips, index {clip_index} out of range"
            )
        if clip_name is not None:
            for c in arr_clips:
                if _clip_name(c) == clip_name:
                    return c
            raise ALSClipNotFound(
                f"Track '{track_name}' has no clip named '{clip_name}' "
                f"(available: {[_clip_name(c) for c in arr_clips]})"
            )
        # Neither index nor name given — return first
        if arr_clips:
            return arr_clips[0]
        raise ALSClipNotFound(f"Track '{track_name}' has no arrangement clips")
    raise ALSClipNotFound(f"No AudioTrack named '{track_name}' in project")


def get_clip_markers(clip: ET.Element) -> List[Marker]:
    """Return [(sec_time, beat_time), ...] for the clip."""
    wms = clip.findall(".//WarpMarkers/WarpMarker")
    return [
        (float(wm.get("SecTime", "0")), float(wm.get("BeatTime", "0")))
        for wm in wms
    ]


def set_clip_markers(clip: ET.Element, markers: Iterable[Marker]) -> int:
    """
    Replace the clip's <WarpMarkers> children with new WarpMarker elements.
    Returns the number of markers written.

    Preserves the parent <WarpMarkers> element and its position; only its
    children are replaced. WarpMarker Id attributes are reassigned 0..N-1.
    """
    wm_parent = clip.find(".//WarpMarkers")
    if wm_parent is None:
        # Need to create <WarpMarkers> and insert it after <WarpMode> if present,
        # otherwise at the end of the AudioClip element.
        wm_parent = ET.SubElement(clip, "WarpMarkers")
    # Clear existing children
    for child in list(wm_parent):
        wm_parent.remove(child)
    count = 0
    for idx, (sec, beat) in enumerate(markers):
        wm = ET.SubElement(
            wm_parent,
            "WarpMarker",
            attrib={
                "Id": str(idx),
                "SecTime": _fmt_float(sec),
                "BeatTime": _fmt_float(beat),
            },
        )
        count += 1
    # Ensure IsWarped is true (otherwise markers are ignored)
    iw = clip.find("IsWarped")
    if iw is not None:
        iw.set("Value", "true")
    # MarkersGenerated must be true as well
    mg = clip.find("MarkersGenerated")
    if mg is not None:
        mg.set("Value", "true")
    return count


def _fmt_float(v: float) -> str:
    """
    Format float the way Ableton does: high precision, no scientific notation.
    Ableton uses values like '1.7029583333333334' and '482.40504527091980'.
    """
    # repr() on a Python float gives round-trippable shortest representation,
    # which closely matches what Ableton writes.
    s = repr(float(v))
    # repr sometimes gives 'inf' / scientific — guard against that
    if "e" in s or "E" in s or s in ("inf", "-inf", "nan"):
        s = f"{v:.16f}".rstrip("0").rstrip(".")
    return s


# ── Song Tempo Automation ───────────────────────────────────────────
# Live 12 stores Song Tempo automation in MainTrack > AutomationEnvelopes
# as FloatEvent elements. AutomationTarget Id="8" is hardcoded for Song Tempo.
# The sentinel Time=-63072000 is Ableton's "before arrangement start" anchor.

TEMPO_AUTOMATION_TARGET_ID = "8"   # AutomationTarget Id for Song Tempo in MainTrack
TEMPO_SENTINEL_TIME = "-63072000"  # Ableton's "before start" anchor time


def find_tempo_envelope(tree: ET.ElementTree) -> ET.Element:
    """
    Find the Song Tempo AutomationEnvelope in <MainTrack><AutomationEnvelopes>.
    Raises ValueError if not found.

    In Live 12 ALS files, the master track is <MainTrack> (not <MasterTrack>).
    Song Tempo has AutomationTarget Id="8" and is referenced by PointeeId Value="8".
    """
    root = tree.getroot()
    main_track = root.find(".//MainTrack")
    if main_track is None:
        raise ValueError(
            "No <MainTrack> element found in ALS. "
            "This may not be a Live 12 project file."
        )
    envelopes_el = main_track.find(".//AutomationEnvelopes/Envelopes")
    if envelopes_el is None:
        raise ValueError("No <AutomationEnvelopes><Envelopes> found in <MainTrack>.")

    for env in envelopes_el.findall("AutomationEnvelope"):
        pointee = env.find(".//EnvelopeTarget/PointeeId")
        if pointee is not None and pointee.get("Value") == TEMPO_AUTOMATION_TARGET_ID:
            return env

    raise ValueError(
        f"No Song Tempo AutomationEnvelope (PointeeId={TEMPO_AUTOMATION_TARGET_ID}) "
        "found in MainTrack. Open the project in Ableton and check that Song Tempo "
        "appears in the automation chooser."
    )


def set_tempo_events(
    env: ET.Element,
    breakpoints: List[Tuple[float, float]],
    hard_cuts: bool = True,
) -> int:
    """
    Replace the <Events> inside a Song Tempo AutomationEnvelope with new FloatEvents.

    breakpoints: [(beat_time, bpm), ...] — one entry per section start.
                 Will be sorted by beat_time automatically.
    hard_cuts:   If True (default), automatically inserts a "hold" event 0.001 beats
                 before each boundary to prevent ramp interpolation between sections.
                 Set False to get linear ramps between breakpoints.

    Always prepends the Ableton sentinel event at Time=-63072000 (Value = first BPM).
    Returns the total number of FloatEvent elements written.
    """
    automation = env.find(".//Automation")
    if automation is None:
        raise ValueError("No <Automation> element inside AutomationEnvelope.")

    events_el = automation.find("Events")
    if events_el is None:
        events_el = ET.SubElement(automation, "Events")
    else:
        for child in list(events_el):
            events_el.remove(child)

    if not breakpoints:
        return 0

    sorted_bps: List[Tuple[float, float]] = sorted(breakpoints, key=lambda x: x[0])
    first_bpm = sorted_bps[0][1]

    # Build the full event list
    events: List[Tuple[float, float]] = []

    if hard_cuts and len(sorted_bps) > 1:
        # For each boundary, add a hold event just before the cut.
        # Pattern:  [..., (beat_N - 0.001, prev_bpm), (beat_N, new_bpm), ...]
        for i, (beat, bpm) in enumerate(sorted_bps):
            if i == 0:
                events.append((beat, bpm))
            else:
                prev_bpm = sorted_bps[i - 1][1]
                events.append((beat - 0.001, prev_bpm))   # hold previous BPM until cut
                events.append((beat, bpm))                 # hard cut to new BPM
    else:
        events = list(sorted_bps)

    # Write sentinel + actual events
    count = 0
    ET.SubElement(events_el, "FloatEvent", attrib={
        "Id": str(count),
        "Time": TEMPO_SENTINEL_TIME,
        "Value": _fmt_float(first_bpm),
    })
    count += 1

    for beat, bpm in events:
        ET.SubElement(events_el, "FloatEvent", attrib={
            "Id": str(count),
            "Time": _fmt_float(beat),
            "Value": _fmt_float(bpm),
        })
        count += 1

    return count


def get_tempo_events(env: ET.Element) -> List[Tuple[float, float]]:
    """
    Return the existing FloatEvents in a Song Tempo AutomationEnvelope,
    excluding the sentinel (Time < 0).
    Returns [(beat_time, bpm), ...] sorted by beat_time.
    """
    result = []
    for ev in env.findall(".//Events/FloatEvent"):
        t = float(ev.get("Time", "0"))
        v = float(ev.get("Value", "0"))
        if t >= 0:
            result.append((t, v))
    return sorted(result, key=lambda x: x[0])


def set_tempo_automation(
    tree: ET.ElementTree,
    breakpoints: List[Tuple[float, float]],
    hard_cuts: bool = True,
) -> int:
    """
    Write Song Tempo automation to a Live 12 ALS ElementTree.

    breakpoints: [(beat_time, bpm), ...] — one per section start.
    hard_cuts:   True (default) = instant tempo cuts; False = linear ramps.

    Returns total number of FloatEvent elements written (including sentinel).

    Workflow:
        tree = read_als("project.als")
        count = set_tempo_automation(tree, [(0, 123.75), (132, 101.25), ...])
        write_als(tree, "project.als", backup=True)
        # Then in Ableton: File > Revert, or close & reopen
    """
    env = find_tempo_envelope(tree)
    return set_tempo_events(env, breakpoints, hard_cuts=hard_cuts)


def read_tempo_automation(tree: ET.ElementTree) -> List[Tuple[float, float]]:
    """
    Read existing Song Tempo automation breakpoints from the ALS file.
    Returns [(beat_time, bpm), ...] sorted by beat_time (sentinel excluded).
    """
    env = find_tempo_envelope(tree)
    return get_tempo_events(env)


# ── MIDI Track Device Parameter Automation ───────────────────────────
# In a Live 12 ALS, each MidiTrack has an <AutomationEnvelopes><Envelopes>
# element as a direct child. Each parameter that can be automated is referenced
# by its AutomationTarget Id (a unique integer in the ALS).
# The sentinel FloatEvent (Time=-63072000) sets the value before the arrangement.

def set_midi_track_automation(
    tree: ET.ElementTree,
    track_name: str,
    pointee_id: str,
    breakpoints: List[Tuple[float, float]],
    default_value: Optional[float] = None,
) -> int:
    """
    Write Arrangement automation for a device parameter on a MidiTrack.

    track_name:   EffectiveName of the target MidiTrack.
    pointee_id:   AutomationTarget Id (as string) of the device parameter.
    breakpoints:  [(beat_time, raw_value), ...] — exact FloatEvents to write
                  (plus the sentinel). Will be sorted by beat_time.
    default_value: Value for the sentinel event (Time=-63072000). If None,
                  uses the value of the first breakpoint.

    Creates <AutomationEnvelopes><Envelopes> if not present.
    Replaces any existing AutomationEnvelope for this pointee_id.
    Returns total number of FloatEvent elements written (including sentinel).
    """
    root = tree.getroot()
    track = None
    for t in root.findall(".//MidiTrack"):
        el = t.find(".//EffectiveName")
        if el is not None and el.get("Value", "") == track_name:
            track = t
            break
    if track is None:
        raise ALSClipNotFound(f"No MidiTrack named {track_name!r}")

    # Find or create AutomationEnvelopes/Envelopes directly under the track
    ae = track.find("AutomationEnvelopes")
    if ae is None:
        ae = ET.SubElement(track, "AutomationEnvelopes")
    envs = ae.find("Envelopes")
    if envs is None:
        envs = ET.SubElement(ae, "Envelopes")

    # Find or create the AutomationEnvelope for this pointee_id
    env = None
    for candidate in envs.findall("AutomationEnvelope"):
        pid = candidate.find(".//EnvelopeTarget/PointeeId")
        if pid is not None and pid.get("Value") == pointee_id:
            env = candidate
            break

    if env is None:
        next_id = str(len(list(envs)))
        env = ET.SubElement(envs, "AutomationEnvelope", attrib={"Id": next_id})
        target_el = ET.SubElement(env, "EnvelopeTarget")
        ET.SubElement(target_el, "PointeeId", attrib={"Value": pointee_id})
        automation = ET.SubElement(env, "Automation")
        events_el = ET.SubElement(automation, "Events")
        transform = ET.SubElement(automation, "AutomationTransformViewState")
        ET.SubElement(transform, "IsTransformPending", attrib={"Value": "false"})
        ET.SubElement(transform, "TimeAndValueTransforms")
    else:
        automation = env.find("Automation")
        if automation is None:
            automation = ET.SubElement(env, "Automation")
        events_el = automation.find("Events")
        if events_el is None:
            events_el = ET.SubElement(automation, "Events")
        else:
            for child in list(events_el):
                events_el.remove(child)

    sorted_bps = sorted(breakpoints, key=lambda x: x[0])
    sentinel_val = default_value if default_value is not None else sorted_bps[0][1]

    count = 0
    ET.SubElement(events_el, "FloatEvent", attrib={
        "Id": str(count),
        "Time": TEMPO_SENTINEL_TIME,
        "Value": _fmt_float(sentinel_val),
    })
    count += 1
    for beat, val in sorted_bps:
        ET.SubElement(events_el, "FloatEvent", attrib={
            "Id": str(count),
            "Time": _fmt_float(beat),
            "Value": _fmt_float(val),
        })
        count += 1

    return count


def get_midi_track_automation(
    tree: ET.ElementTree,
    track_name: str,
    pointee_id: str,
) -> List[Tuple[float, float]]:
    """
    Read existing automation breakpoints for a MIDI track device parameter.
    Returns [(beat_time, raw_value), ...] sorted by beat_time (sentinel excluded).
    """
    root = tree.getroot()
    for track in root.findall(".//MidiTrack"):
        el = track.find(".//EffectiveName")
        if el is not None and el.get("Value", "") == track_name:
            ae = track.find("AutomationEnvelopes")
            if ae is None:
                return []
            envs = ae.find("Envelopes")
            if envs is None:
                return []
            for env in envs.findall("AutomationEnvelope"):
                pid = env.find(".//EnvelopeTarget/PointeeId")
                if pid is not None and pid.get("Value") == pointee_id:
                    result = []
                    for ev in env.findall(".//Events/FloatEvent"):
                        t = float(ev.get("Time", "0"))
                        v = float(ev.get("Value", "0"))
                        if t >= 0:
                            result.append((t, v))
                    return sorted(result, key=lambda x: x[0])
    return []


# ── Wavetable Mod Matrix ─────────────────────────────────────────────
# Wavetable is stored as <InstrumentVector> in the ALS XML.
# ModulationConnections holds 52 slots (ModulationConnectionsForInstrumentVector),
# each with 13 source amounts (ModulationAmounts.0 .. ModulationAmounts.12):
#   Source indices: 0=Env1, 1=Env2, 2=Env3, 3=LFO1, 4=LFO2,
#                   5=Velocity, 6=Key, 7=Random, 8..12=MIDI sources
# Isochronic routing slots:
#   Id="4"  TargetId=Voice_Oscillator1_Pan  → LFO2 → Pan
#   Id="5"  TargetId=Voice_Oscillator1_Gain → LFO1 → Volume

LFO1_SOURCE_INDEX = 3
LFO2_SOURCE_INDEX = 4
OSC1_GAIN_SLOT_ID = "5"
OSC1_PAN_SLOT_ID  = "4"


def find_midi_track_by_name(
    tree: ET.ElementTree,
    track_name: str,
) -> ET.Element:
    """Find a MidiTrack by its EffectiveName; raises ALSClipNotFound if absent."""
    root = tree.getroot()
    for track in root.findall(".//MidiTrack"):
        el = track.find(".//EffectiveName")
        if el is not None and el.get("Value", "") == track_name:
            return track
    raise ALSClipNotFound(f"No MidiTrack named {track_name!r}")


def _find_instrument_vector(track_el: ET.Element) -> Optional[ET.Element]:
    """Return the InstrumentVector (Wavetable) inside a MidiTrack, or None."""
    return track_el.find(".//InstrumentVector")


def _set_mod_amount(iv: ET.Element, slot_id: str, source_index: int, amount: float) -> None:
    """Set ModulationAmounts.<source_index> in the given ModulationConnections slot."""
    mc = iv.find("ModulationConnections")
    if mc is None:
        raise ValueError("InstrumentVector has no ModulationConnections element")
    slot = next(
        (s for s in mc.findall("ModulationConnectionsForInstrumentVector")
         if s.get("Id") == slot_id),
        None,
    )
    if slot is None:
        raise ValueError(f"Mod matrix slot Id={slot_id!r} not found")
    key = f"ModulationAmounts.{source_index}"
    el = slot.find(key)
    if el is None:
        raise ValueError(f"<{key}> not found in slot {slot_id}")
    el.set("Value", _fmt_float(amount))


def get_wavetable_mod_state(iv: ET.Element) -> List[dict]:
    """
    Return all non-zero modulation connections in an InstrumentVector's mod matrix.
    Returns [{"slot_id", "target_id", "target_name", "amounts": {src_idx: value}}, ...]
    """
    mc = iv.find("ModulationConnections")
    if mc is None:
        return []
    result = []
    for slot in mc.findall("ModulationConnectionsForInstrumentVector"):
        amounts = {}
        for i in range(13):
            el = slot.find(f"ModulationAmounts.{i}")
            if el is not None:
                v = float(el.get("Value", "0"))
                if v != 0.0:
                    amounts[i] = v
        if amounts:
            tn_el = slot.find("TargetName")
            result.append({
                "slot_id": slot.get("Id", "?"),
                "target_id": slot.get("TargetId", "?"),
                "target_name": tn_el.get("Value", "?") if tn_el is not None else "?",
                "amounts": amounts,
            })
    return result


def set_wavetable_isochronic_routing(
    tree: ET.ElementTree,
    track_name: str,
    lfo1_gain_amount: float = 0.75,
    lfo2_pan_amount: float = 0.4,
) -> dict:
    """
    Patch isochronic LFO routing for a Wavetable (_Main) track:
      LFO 1 (source 3) → Osc 1 Gain  [Id=5] — volume tremolo
      LFO 2 (source 4) → Osc 1 Pan   [Id=4] — panning sweep

    Returns a summary dict. Call write_als() afterwards to persist.
    """
    track = find_midi_track_by_name(tree, track_name)
    iv = _find_instrument_vector(track)
    if iv is None:
        raise ValueError(f"Track {track_name!r} has no InstrumentVector (Wavetable) device")
    _set_mod_amount(iv, OSC1_GAIN_SLOT_ID, LFO1_SOURCE_INDEX, lfo1_gain_amount)
    _set_mod_amount(iv, OSC1_PAN_SLOT_ID,  LFO2_SOURCE_INDEX, lfo2_pan_amount)
    return {
        "track": track_name,
        "lfo1_gain_amount": lfo1_gain_amount,
        "lfo2_pan_amount": lfo2_pan_amount,
    }


# ── Transform Helpers ───────────────────────────────────────────────
def compute_offset_markers(
    source: Iterable[Marker],
    offset: float,
) -> List[Marker]:
    """
    Return new markers with sec_time shifted by `offset`.
    beat_time is preserved. Negative sec_times are clamped to 0.
    """
    out: List[Marker] = []
    for sec, beat in source:
        new_sec = sec + offset
        if new_sec < 0.0:
            new_sec = 0.0
        out.append((new_sec, beat))
    return out


def validate_markers(markers: List[Marker]) -> List[str]:
    """
    Sanity-check a marker list. Returns a list of problem descriptions
    (empty list = all good).
    """
    problems: List[str] = []
    if not markers:
        problems.append("empty marker list")
        return problems
    if markers[0][1] != 0.0:
        problems.append(f"first marker BeatTime is {markers[0][1]}, expected 0")
    beats = [b for _, b in markers]
    if beats != sorted(beats):
        problems.append("markers not sorted by BeatTime")
    dups = [b for b in beats if beats.count(b) > 1]
    if dups:
        # duplicate BeatTimes are OK in Ableton (anchor pairs) — just report
        problems.append(f"duplicate BeatTimes found (may be intentional): {set(dups)}")
    secs = [s for s, _ in markers]
    if secs != sorted(secs):
        problems.append("markers not sorted by SecTime")
    return problems


# ── File-open Detection ─────────────────────────────────────────────
def is_als_locked(path: str | Path) -> bool:
    """
    Heuristic: on Windows, if Ableton has the .als open, attempting to
    open it in append mode fails with PermissionError.
    Returns True if the file appears locked.
    """
    try:
        with open(path, "ab"):
            pass
        return False
    except (PermissionError, OSError):
        return True


# ── CLI ─────────────────────────────────────────────────────────────
def _cli_read(args) -> int:
    tree = read_als(args.path)
    if args.track is None:
        # Summary mode
        audio_tracks = tree.getroot().findall(".//AudioTrack")
        print(f"AudioTracks: {len(audio_tracks)}")
        for ti, track in enumerate(audio_tracks):
            tname = _track_name(track)
            clips = track.findall(".//ArrangerAutomation//AudioClip")
            print(f"  [{ti}] {tname!r}: {len(clips)} arrangement clips")
            for ci, clip in enumerate(clips[:3]):
                wms = clip.findall(".//WarpMarkers/WarpMarker")
                print(f"      [{ci}] {_clip_name(clip)!r} | markers={len(wms)}")
            if len(clips) > 3:
                print(f"      ... +{len(clips) - 3} more")
        return 0
    clip = find_clip(tree, args.track, args.clip, args.clip_index)
    markers = get_clip_markers(clip)
    print(f"Track={args.track!r} Clip={_clip_name(clip)!r}")
    print(f"Markers: {len(markers)}")
    if args.json:
        print(json.dumps([{"sec_time": s, "beat_time": b} for s, b in markers], indent=2))
    else:
        for idx, (s, b) in enumerate(markers[:10]):
            print(f"  [{idx}] sec={s:.9f} beat={b}")
        if len(markers) > 10:
            print(f"  ... +{len(markers) - 10} more")
    return 0


def _cli_derive(args) -> int:
    """
    Read source markers from one clip, apply offset, write to target clip.
    """
    tree = read_als(args.path)

    # Source
    src_clip = find_clip(tree, args.source_track, args.source_clip, None)
    src_markers = get_clip_markers(src_clip)
    print(f"Source: {args.source_track!r}/{_clip_name(src_clip)!r} → {len(src_markers)} markers")

    # Transform
    new_markers = compute_offset_markers(src_markers, args.offset)
    problems = validate_markers(new_markers)
    if problems:
        print("⚠  Validation warnings:")
        for p in problems:
            print(f"   - {p}")

    # Target
    tgt_clip = find_clip(tree, args.target_track, args.target_clip, None)
    print(f"Target: {args.target_track!r}/{_clip_name(tgt_clip)!r}")

    if args.dry_run:
        print(f"[DRY RUN] Would write {len(new_markers)} markers (offset={args.offset:+.4f}s)")
        for idx, (s, b) in enumerate(new_markers[:5]):
            print(f"  [{idx}] sec={s:.6f} beat={b}")
        return 0

    # Safety check: is Ableton holding the file?
    if is_als_locked(args.path):
        msg = f"⚠  File appears locked (Ableton may have {args.path} open)."
        if args.force:
            print(msg + " Proceeding anyway (--force).")
        else:
            print(msg + " Use --force to override or close Ableton first.")
            return 2

    count = set_clip_markers(tgt_clip, new_markers)
    backup = write_als(tree, args.path, backup=not args.no_backup)
    print(f"✓ Wrote {count} markers. Backup: {backup}")
    print("→ In Ableton: close & reopen the project (or toggle warping off/on the clip)")
    return 0


def _cli_write(args) -> int:
    tree = read_als(args.path)
    with open(args.markers_json, "r", encoding="utf-8") as f:
        payload = json.load(f)
    markers: List[Marker] = [(float(m["sec_time"]), float(m["beat_time"])) for m in payload]
    problems = validate_markers(markers)
    if problems:
        print("⚠  Validation warnings:")
        for p in problems:
            print(f"   - {p}")

    clip = find_clip(tree, args.track, args.clip, args.clip_index)
    print(f"Target: {args.track!r}/{_clip_name(clip)!r}")

    if args.dry_run:
        print(f"[DRY RUN] Would write {len(markers)} markers")
        return 0

    if is_als_locked(args.path):
        msg = f"⚠  File appears locked (Ableton may have {args.path} open)."
        if args.force:
            print(msg + " Proceeding anyway (--force).")
        else:
            print(msg + " Use --force to override.")
            return 2

    count = set_clip_markers(clip, markers)
    backup = write_als(tree, args.path, backup=not args.no_backup)
    print(f"✓ Wrote {count} markers. Backup: {backup}")
    return 0


def _cli_validate(args) -> int:
    try:
        tree = read_als(args.path)
    except ALSFormatError as e:
        print(f"✗ Invalid ALS: {e}")
        return 1
    root = tree.getroot()
    print(f"✓ Valid ALS")
    print(f"  Version: {root.get('Creator', '?')} ({root.get('MajorVersion', '?')}.{root.get('MinorVersion', '?')})")
    print(f"  AudioTracks: {len(root.findall('.//AudioTrack'))}")
    print(f"  AudioClips total: {len(root.findall('.//AudioClip'))}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    # Windows consoles may use cp1252; force UTF-8 for stdout so our output
    # symbols render correctly regardless of locale.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

    p = argparse.ArgumentParser(
        description="Read/write Ableton .als warp markers directly (bypasses Live API deadlock).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # read
    r = sub.add_parser("read", help="List tracks/clips or dump markers of one clip")
    r.add_argument("path")
    r.add_argument("--track", help="AudioTrack EffectiveName (optional)")
    r.add_argument("--clip", help="Clip name (optional; if omitted, uses --clip-index or first)")
    r.add_argument("--clip-index", type=int, default=None)
    r.add_argument("--json", action="store_true", help="Emit markers as JSON")
    r.set_defaults(func=_cli_read)

    # write
    w = sub.add_parser("write", help="Write markers from JSON file to a clip")
    w.add_argument("path")
    w.add_argument("--track", required=True)
    w.add_argument("--clip", default=None)
    w.add_argument("--clip-index", type=int, default=None)
    w.add_argument("--markers-json", required=True, help="Path to JSON array of {sec_time, beat_time}")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--no-backup", action="store_true")
    w.add_argument("--force", action="store_true", help="Write even if file appears locked")
    w.set_defaults(func=_cli_write)

    # derive
    d = sub.add_parser("derive", help="Copy markers from source clip to target clip with SecTime offset")
    d.add_argument("path")
    d.add_argument("--source-track", required=True)
    d.add_argument("--source-clip", default=None)
    d.add_argument("--target-track", required=True)
    d.add_argument("--target-clip", default=None)
    d.add_argument("--offset", type=float, required=True, help="Seconds to add to each SecTime")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--no-backup", action="store_true")
    d.add_argument("--force", action="store_true")
    d.set_defaults(func=_cli_derive)

    # validate
    v = sub.add_parser("validate", help="Check that path is a valid .als file")
    v.add_argument("path")
    v.set_defaults(func=_cli_validate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
