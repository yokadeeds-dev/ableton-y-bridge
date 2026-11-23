"""Tools that work on .als project files instead of the running Live.

Used where Live's API ends: bulk warp markers, tempo automation, Wavetable
modulation routing, and file-level snapshots. A changed .als only takes
effect after the project is reloaded in Live.
"""

from __future__ import annotations

import os
import shutil
import time

from .. import als_warp_writer as als
from .. import winkeys
from ..coerce import BoolLike, FloatLike, IntLike, opt_int, to_bool, to_float, to_list
from ..core import DESTRUCTIVE, READ, live, note_outside_change, tool
from ..link import LiveError

RELOAD_HINT = "Reload the project in Live (open the same file again without saving) to see it."
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _truthy(value) -> bool:
    try:
        return to_bool(value)
    except ValueError:
        return False


def _snapshot_dir(given: str) -> str:
    chosen = (given or "").strip() or os.environ.get("ABLETON_MCP_SNAPSHOT_DIR", "").strip()
    return chosen or os.path.join(_PROJECT_ROOT, "session_snapshots")


def _open_tree(als_path: str):
    try:
        return als.read_als(als_path)
    except (FileNotFoundError, als.ALSFormatError) as problem:
        raise ValueError(f"cannot read {als_path}: {problem}")


def _lock_note(als_path: str, force: bool) -> str:
    """Refuse to write a file Live has open unless forced; return a warning."""
    if not als.is_als_locked(als_path):
        return ""
    if not force:
        raise ValueError(f"{als_path} is open in another program (probably Live). "
                         "Close the project there or pass force=true.")
    return " WARNING: the file was open elsewhere; Live may overwrite it on save."


def _pick_clip(tree, track_name: str, clip_name: str, clip_index):
    try:
        return als.find_clip(tree, track_name, clip_name or None, clip_index)
    except als.ALSClipNotFound as problem:
        raise ValueError(str(problem))


def _marker_warnings(markers) -> str:
    problems = als.validate_markers(markers)
    return f" Warnings: {'; '.join(problems)}." if problems else ""


@tool(DESTRUCTIVE)
def als_warp_write(als_path: str, track_name: str, markers_json: str, clip_name: str = "",
                   clip_index: IntLike = -1, backup: BoolLike = True,
                   force: BoolLike = False, confirm: BoolLike = False) -> str:
    """Write warp markers of one audio clip directly into a .als file.

    For large marker sets, or when Live's marker API is not enough. The
    clip's existing markers are replaced.

    - als_path: full path of the .als file
    - track_name: name of the audio track as shown in Live
    - markers_json: JSON array of {"sec_time": seconds in the audio file,
                    "beat_time": beats}
    - clip_name: name of the clip; if empty, clip_index decides
    - clip_index: Arrangement clip index on that track; -1 = first clip
    - backup: keep a timestamped copy of the file first (default true)
    - force: write even if the file is open in Live (default false)
    - confirm: must be true for the tool to run. Ask the user first; do not
               set it on your own initiative.
    """
    try:
        markers = [(float(m["sec_time"]), float(m["beat_time"]))
                   for m in to_list(markers_json, "markers_json")]
    except (KeyError, TypeError) as problem:
        raise ValueError(f"each marker needs sec_time and beat_time ({problem})")
    tree = _open_tree(als_path)
    wanted_index = opt_int(clip_index, "clip_index")
    clip = _pick_clip(tree, track_name, clip_name, None if wanted_index in (None, -1) else wanted_index)
    note = _marker_warnings(markers) + _lock_note(als_path, to_bool(force, "force"))
    count = als.set_clip_markers(clip, markers)
    saved_copy = als.write_als(tree, als_path, backup=to_bool(backup, "backup"))
    note_outside_change(f"Wrote {count} warp markers into {os.path.basename(als_path)} "
                        f"('{track_name}'); backup: {saved_copy or 'none'}")
    return (f"Wrote {count} warp markers to '{track_name}' / '{als._clip_name(clip)}'. "
            f"Backup: {saved_copy or 'none'}.{note} {RELOAD_HINT}")


@tool(DESTRUCTIVE, unless=lambda given: _truthy(given.get("dry_run")))
def als_warp_derive(als_path: str, source_track: str, target_track: str,
                    offset_seconds: FloatLike, source_clip: str = "", target_clip: str = "",
                    backup: BoolLike = True, force: BoolLike = False,
                    dry_run: BoolLike = False, confirm: BoolLike = False) -> str:
    """Copy the warp markers of one clip to another clip, shifted in time.

    Typical case: stems rendered from the same song where one file starts a
    known amount earlier or later. Warp one stem by hand, derive the others.

    - als_path: full path of the .als file
    - source_track: audio track to read markers from
    - target_track: audio track to write markers to
    - offset_seconds: added to every marker's position in the audio file
    - source_clip, target_clip: clip names; empty = first clip of the track
    - backup: keep a timestamped copy first (default true)
    - force: write even if the file is open in Live
    - dry_run: only report what would be written (needs no confirm)
    - confirm: must be true for the tool to run. Ask the user first; do not
               set it on your own initiative.
    """
    offset = to_float(offset_seconds, "offset_seconds")
    tree = _open_tree(als_path)
    source = _pick_clip(tree, source_track, source_clip, None)
    target = _pick_clip(tree, target_track, target_clip, None)
    derived = als.compute_offset_markers(als.get_clip_markers(source), offset)
    note = _marker_warnings(derived)
    where = f"'{target_track}' / '{als._clip_name(target)}'"
    if to_bool(dry_run, "dry_run"):
        sample = ", ".join(f"{sec:.4f}s@{beat:g}" for sec, beat in derived[:3])
        return (f"Dry run: {len(derived)} markers would go to {where} with offset "
                f"{offset:+.4f} s.{note} First: {sample}")
    note += _lock_note(als_path, to_bool(force, "force"))
    count = als.set_clip_markers(target, derived)
    saved_copy = als.write_als(tree, als_path, backup=to_bool(backup, "backup"))
    note_outside_change(f"Derived {count} warp markers into {os.path.basename(als_path)} "
                        f"('{target_track}'); backup: {saved_copy or 'none'}")
    return (f"Wrote {count} markers to {where}, derived from '{source_track}' with offset "
            f"{offset:+.4f} s. Backup: {saved_copy or 'none'}.{note} {RELOAD_HINT}")


@tool(READ)
def als_warp_read(als_path: str, track_name: str = "", clip_name: str = "",
                  clip_index: IntLike = -1) -> str:
    """Read warp markers from a .als file; Live does not need to run.

    - als_path: full path of the .als file
    - track_name: audio track to read; empty lists all audio tracks with
                  their clips and marker counts instead
    - clip_name: clip to read; empty = use clip_index
    - clip_index: Arrangement clip index; -1 = first clip
    """
    tree = _open_tree(als_path)
    if not track_name:
        rows = []
        for number, track in enumerate(tree.getroot().findall(".//AudioTrack")):
            clips = track.findall(".//ArrangerAutomation//AudioClip")
            rows.append(f"[{number}] {als._track_name(track)!r}: {len(clips)} clip(s)")
            for position, clip in enumerate(clips[:3]):
                count = len(clip.findall(".//WarpMarkers/WarpMarker"))
                rows.append(f"    [{position}] {als._clip_name(clip)!r}: {count} markers")
            if len(clips) > 3:
                rows.append(f"    ... {len(clips) - 3} more")
        return "\n".join(rows) or "No audio tracks in this file."
    wanted_index = opt_int(clip_index, "clip_index")
    clip = _pick_clip(tree, track_name, clip_name, None if wanted_index in (None, -1) else wanted_index)
    markers = als.get_clip_markers(clip)
    return {"track": track_name, "clip": als._clip_name(clip), "count": len(markers),
            "markers": [{"sec_time": sec, "beat_time": beat} for sec, beat in markers]}


@tool(DESTRUCTIVE, unless=lambda given: str(given.get("breakpoints", "")).strip() in ("", "[]"))
def set_tempo_automation(als_path: str, breakpoints: str, hard_cuts: BoolLike = True,
                         backup: BoolLike = True, confirm: BoolLike = False) -> str:
    """Write song tempo automation into a .als file (Live 12 format).

    Live's API cannot create tempo automation, so the project file is
    edited: the same data Live stores when you draw the tempo envelope.

    - als_path: full path of the saved .als file
    - breakpoints: JSON array of {"beat": position, "bpm": tempo}, one per
                   section start; an empty array returns the existing events
    - hard_cuts: true = tempo jumps at each breakpoint (a hold point is
                 inserted just before it); false = linear ramps between points
    - backup: keep a timestamped copy first (default true)
    - confirm: must be true to write (reading with an empty array needs none).
               Ask the user first; do not set it on your own initiative.
    """
    try:
        points = [(float(p["beat"]), float(p["bpm"]))
                  for p in to_list(breakpoints, "breakpoints")]
    except (KeyError, TypeError) as problem:
        raise ValueError(f"each breakpoint needs beat and bpm ({problem})")
    tree = _open_tree(als_path)
    if not points:
        return {"mode": "read_existing", "als_path": als_path,
                "events": [{"beat": beat, "bpm": bpm}
                           for beat, bpm in als.read_tempo_automation(tree)]}
    cuts = to_bool(hard_cuts, "hard_cuts")
    written = als.set_tempo_automation(tree, points, hard_cuts=cuts)
    saved_copy = als.write_als(tree, als_path, backup=to_bool(backup, "backup"))
    note_outside_change(f"Wrote tempo automation ({len(points)} sections) into "
                        f"{os.path.basename(als_path)}; backup: {saved_copy or 'none'}")
    return {"events_written": written, "sections": len(points), "hard_cuts": cuts,
            "als_path": als_path, "backup": str(saved_copy) if saved_copy else None,
            "next_step": RELOAD_HINT}


@tool(DESTRUCTIVE)
def set_wavetable_mod_routing(als_path: str, track_names: str,
                              lfo1_gain_amount: FloatLike = 0.75,
                              lfo2_pan_amount: FloatLike = 0.4,
                              backup: BoolLike = True, confirm: BoolLike = False) -> str:
    """Patch the modulation matrix of Wavetable devices inside a .als file.

    Sets LFO 1 -> Osc 1 Gain (tremolo) and LFO 2 -> Osc 1 Pan (auto-pan) on
    the Wavetable of each named MIDI track. The modulation matrix is not
    reachable through Live's API, hence the file edit.

    - als_path: full path of the saved .als file
    - track_names: JSON array of MIDI track names
    - lfo1_gain_amount: depth of LFO 1 on Osc 1 gain, 0..1
    - lfo2_pan_amount: depth of LFO 2 on Osc 1 pan, 0..1
    - backup: keep a timestamped copy first (default true)
    - confirm: must be true for the tool to run. Ask the user first; do not
               set it on your own initiative.
    """
    names = to_list(track_names, "track_names")
    gain, pan = to_float(lfo1_gain_amount, "lfo1_gain_amount"), to_float(lfo2_pan_amount, "lfo2_pan_amount")
    tree = _open_tree(als_path)
    patched, failed = [], []
    for name in names:
        try:
            patched.append(als.set_wavetable_isochronic_routing(tree, str(name), gain, pan))
        except Exception as problem:
            failed.append({"track": name, "error": str(problem)})
    if not patched:
        return {"status": "nothing written", "errors": failed}
    saved_copy = als.write_als(tree, als_path, backup=to_bool(backup, "backup"))
    note_outside_change(f"Patched Wavetable modulation of {len(patched)} track(s) in "
                        f"{os.path.basename(als_path)}; backup: {saved_copy or 'none'}")
    return {"patched_tracks": len(patched), "results": patched, "errors": failed,
            "lfo1_gain_amount": gain, "lfo2_pan_amount": pan, "als_path": als_path,
            "backup": str(saved_copy) if saved_copy else None, "next_step": RELOAD_HINT}


@tool(DESTRUCTIVE)
def snapshot_session(label: str = "", snapshot_dir: str = "",
                     confirm: BoolLike = False) -> str:
    """Save the Live Set and keep a timestamped copy of its .als file.

    Call before larger changes (restructuring, mastering chains, bulk note
    or warp edits) to have a state to go back to. The Set must already have
    been saved under a name. Saving is done by typing Ctrl+S into Live's
    window (Windows only; Live comes to the front), because Live's API has
    no save call.

    - label: short tag for the copy's file name, e.g. 'before_mastering'
    - snapshot_dir: folder for the copies; default is session_snapshots/
                    next to this server (or ABLETON_MCP_SNAPSHOT_DIR)
    - confirm: must be true, because the Set's file is overwritten by the
               save. Ask the user first; do not set it on your own initiative.
    """
    source = live.call("get_session_info").get("set_path") or ""
    if not source or not os.path.isfile(source):
        raise LiveError("the Set has never been saved, so there is no file to copy. "
                        "Save it under a name in Live first.", "not_found")
    before = os.path.getmtime(source)
    note = ""
    try:
        winkeys.type_into_live([(winkeys.VK_CONTROL, winkeys.VK_S)])
        deadline = time.time() + 10.0
        while os.path.getmtime(source) <= before and time.time() < deadline:
            time.sleep(0.25)
            if winkeys.dialog_appeared():
                break
        if winkeys.dialog_appeared():
            note = ("NOTE: Live answered Ctrl+S with a dialog (for example because the Set "
                    "is not inside a Project folder). Answer it in Live. The copy holds the "
                    "last saved state.")
        elif os.path.getmtime(source) <= before:
            note = ("NOTE: Ctrl+S was sent but the file did not change (nothing to save, "
                    "or the keys did not reach Live). The copy holds the last saved state.")
    except winkeys.KeysUnavailable as problem:
        note = (f"NOTE: could not save first ({problem}). "
                "The copy holds the last saved state.")
    folder = _snapshot_dir(snapshot_dir)
    os.makedirs(folder, exist_ok=True)
    tag = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label.strip())
    stem = os.path.splitext(os.path.basename(source))[0]
    target = os.path.join(folder, f"{stem}__{time.strftime('%Y%m%d_%H%M%S')}"
                                  f"{'_' + tag if tag else ''}.als")
    shutil.copy2(source, target)
    note_outside_change(f"Saved the Set (Ctrl+S) and copied it to {os.path.basename(target)}"
                        if not note else f"Copied the last saved Set to "
                        f"{os.path.basename(target)} (save did not go through)")
    report = [f"Snapshot: {target}", f"  from: {source}",
              f"  size: {os.path.getsize(target) // 1024} KB"]
    if note:
        report.append("  " + note)
    return "\n".join(report)


@tool(READ)
def list_snapshots(snapshot_dir: str = "") -> str:
    """List the snapshots made by snapshot_session, newest first.

    - snapshot_dir: folder to look in; default as in snapshot_session
    """
    folder = _snapshot_dir(snapshot_dir)
    if not os.path.isdir(folder):
        return f"No snapshot folder yet: {folder}"
    files = [name for name in os.listdir(folder) if name.lower().endswith(".als")]
    files.sort(key=lambda name: os.path.getmtime(os.path.join(folder, name)), reverse=True)
    if not files:
        return f"No snapshots in {folder}"
    rows = [f"{len(files)} snapshot(s) in {folder}:"]
    for name in files[:20]:
        full = os.path.join(folder, name)
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(full)))
        rows.append(f"  {stamp}  {os.path.getsize(full) // 1024:>6} KB  {name}")
    if len(files) > 20:
        rows.append(f"  ... {len(files) - 20} older")
    return "\n".join(rows)
