"""Calls every MCP tool once against a running Ableton Live and writes a protocol.

The MCP server is started as a child process and spoken to over stdio with
the MCP client library, i.e. exactly the way an assistant uses it. The
script builds its own tracks and clips at the end of the track list and
never touches existing ones, but it does change tempo, loop, locators and
return A. Run it against a throwaway Set only.

    python tests/live_protocol.py --work-dir <scratch folder> --out docs/LIVE_TEST_PROTOCOL.md

The work folder receives a generated test tone, snapshots and .als copies.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import os
import re
import shutil
import socket
import struct
import sys
import time
import wave

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL, LIMIT, SKIP = "pass", "FAIL", "limit", "skipped"


def write_test_tone(path: str, seconds: float = 8.0, rate: int = 44100) -> None:
    """A click every half second over a quiet 220 Hz tone, peak at -6 dBFS."""
    frames = bytearray()
    for index in range(int(seconds * rate)):
        t = index / rate
        value = 0.1 * math.sin(2 * math.pi * 220.0 * t)
        if (t % 0.5) < 0.01:
            value = 0.5
        frames += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class Run:
    def __init__(self, session: ClientSession, work_dir: str, analyzer_port: int):
        self.session = session
        self.work = work_dir
        self.analyzer_port = analyzer_port
        self.rows = []
        self.called = set()

    async def tool(self, tool_name: str, /, expect=None, verdict_on_error=FAIL,
                   note: str = "", error_code: str = None, **args):
        """Call a tool, judge the answer, remember the row, return the text."""
        name = tool_name
        self.called.add(name)
        started = time.time()
        try:
            result = await self.session.call_tool(name, args)
            text = "\n".join(getattr(part, "text", "") for part in result.content)
            failed = bool(result.isError) or text.startswith("Error")
        except Exception as problem:
            text, failed = f"client exception: {problem!r}", True
        verdict = PASS
        if error_code is not None:
            # This call is expected to be refused with exactly this code.
            if not (failed and f"[{error_code}]" in text):
                verdict = FAIL
                note = (note + f" | expected a refusal with code {error_code}").strip(" |")
        elif failed:
            verdict = verdict_on_error
        elif expect is not None:
            try:
                good = expect(text) if callable(expect) else (expect in text)
            except Exception as problem:
                good, note = False, f"{note} (check raised {problem!r})"
            if not good:
                verdict = FAIL
                note = (note + " | expectation not met").strip(" |")
        self.rows.append({"tool": name, "args": args, "verdict": verdict, "note": note,
                          "ms": int((time.time() - started) * 1000), "answer": text})
        mark = {PASS: "ok  ", FAIL: "FAIL", LIMIT: "lim ", SKIP: "skip"}[verdict]
        print(f"[{mark}] {name} {json.dumps(args, ensure_ascii=False)[:90]} -> "
              f"{text.splitlines()[0][:110] if text else ''}", flush=True)
        return text

    def skip(self, name: str, why: str):
        self.called.add(name)
        self.rows.append({"tool": name, "args": {}, "verdict": SKIP, "note": why, "ms": 0,
                          "answer": ""})
        print(f"[skip] {name}: {why}", flush=True)

    def send_analyzer_frame(self):
        frame = {"lufs_approx": -17.5, "rms_db": -19.0, "peak_db": -4.0,
                 "bands": {"sub": -32.0, "low": -24.0, "mid": -21.0, "high": -27.0, "air": -40.0}}
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out.sendto(json.dumps(frame).encode("utf-8"), ("127.0.0.1", self.analyzer_port))
        out.close()

    async def find_uri(self, path: str, wanted: str, depth: int = 2):
        """Look for a loadable browser item by name below ``path`` (helper, via the tool)."""
        text = await self.session.call_tool("get_browser_items_at_path",
                                            {"path": path, "limit": 0})
        text = "\n".join(getattr(part, "text", "") for part in text.content)
        folders = []
        for line in text.splitlines():
            match = re.match(r"\s+\[(L|F)\] (.*?) \| (.*)$", line)
            if not match:
                continue
            kind, name, uri = match.groups()
            if kind == "L" and name.strip().lower() == wanted.lower():
                return uri.strip()
            if kind == "F":
                folders.append(name.strip())
        if depth > 0:
            for folder in folders:
                found = await self.find_uri(f"{path}/{folder}", wanted, depth - 1)
                if found:
                    return found
        return None


async def scenario(run: Run) -> None:
    t = run.tool
    work = run.work
    # A new name per run: Live keeps the file of the previous run open.
    tone = os.path.join(work, time.strftime("v2_test_tone_%H%M%S.wav"))
    write_test_tone(tone)

    # -- bridge ------------------------------------------------------------
    status = json.loads(await t("bridge_status", expect='"bridge_version": "2.1.0"'))
    await t("hot_reload", expect="Hot reload ok")
    again = json.loads(await t("bridge_status", note="after hot reload",
                               expect=lambda s: json.loads(s)["reload_count"]
                               == status["reload_count"] + 1))
    script_dir = again["script_dir"]
    probe = os.path.join(script_dir, "handlers", "zz_reload_probe.py")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write("from ..registry import READ, command\n\n\n"
                     "@command('reload_probe', zone=READ, summary='written by the live test')\n"
                     "def reload_probe(live):\n    return {'probe': True}\n")
    await t("hot_reload", expect="New: reload_probe", note="new handler file picked up from disk")
    os.remove(probe)
    await t("hot_reload", expect="Gone: reload_probe", note="removed handler file dropped")
    await t("set_warp_markers_batch", track_index="version", clip_index=0, markers="[]",
            expect="file_hash", note="old keyword spelling of the version check")

    # -- session and transport ---------------------------------------------
    info = json.loads(await t("get_session_info", expect='"tempo"'))
    first = info["track_count"]
    original_tempo = info["tempo"]
    await t("set_tempo", tempo=123, expect="123.00")
    await t("jump_to_time", time=8, expect="8.000")
    await t("set_arrangement_loop", start=4, length=8, enabled=True, expect="4 to 12")
    await t("set_arrangement_loop", start=0, length=4, enabled=False, note="switch loop off again",
            expect="off")
    await t("set_arrangement_record", enabled=True, expect="ON")
    await t("set_arrangement_record", enabled=False, expect="off")
    await t("switch_view", view="Arranger", expect="Arranger")
    await t("focus_view", view="Session", expect="Session")

    # -- tracks --------------------------------------------------------------
    midi, audio, audio2, drums = first, first + 1, first + 2, first + 3
    await t("create_midi_track", index=-1, expect=f"index {midi}")
    await t("create_audio_track", index=-1, expect=f"index {audio}")
    await t("create_audio_track", index=-1, expect=f"index {audio2}", note="second audio track")
    await t("create_midi_track", index=-1, expect=f"index {drums}", note="track for the drum kit")
    await t("set_track_name", track_index=midi, name="v2 Test MIDI", expect="v2 Test MIDI")
    await t("set_track_name", track_index=audio, name="v2 Test Audio", expect="v2 Test Audio")
    await t("set_track_name", track_index=audio2, name="v2 Test Audio 2", expect="Audio 2")
    await t("get_track_info", track_index=midi, expect='"kind": "midi"')
    await t("set_track_volume", track_index=midi, volume_db=-6, expect="-6.0 dB")
    await t("set_track_volume", track_index=midi, volume_db="-inf", expect="-inf dB",
            note="closed fader")
    await t("set_track_volume", track_index=midi, volume_db=-12, expect="-12.0 dB")
    await t("set_track_mute", track_index=midi, mute=True, expect="muted")
    await t("set_track_mute", track_index=midi, mute=False, expect="audible")
    await t("set_track_color", track_index=midi, color_index=12, expect="palette colour 12")
    returns = json.loads(await t("get_return_tracks", expect='"returns"'))["returns"]
    if returns:
        await t("set_track_send", track_index=midi, send_index=0, value=0.25, expect="0.250")
        await t("set_return_track_volume", index=0, volume=0.7, expect="Return 0")
        await t("set_return_track_volume", index=0, volume=0.85, expect="0.0 dB",
                note="back to unity")
    else:
        run.skip("set_track_send", "the Set has no return tracks")
        run.skip("set_return_track_volume", "the Set has no return tracks")
    await t("select_tracks", track_indices=[midi, audio], expect=f"Selected track {midi}")
    await t("freeze_track", track_index=midi, freeze=True, verdict_on_error=FAIL,
            expect="no freeze call", note="Live's API cannot freeze; tool reports state only")

    # -- clips and notes -----------------------------------------------------
    notes = [{"pitch": 60, "start_time": 0, "duration": 0.5, "velocity": 100},
             {"pitch": 64, "start_time": 1, "duration": 0.5, "velocity": 90},
             {"pitch": 67, "start_time": 2, "duration": 0.5, "velocity": 90},
             {"pitch": 72, "start_time": 3, "duration": 0.5, "velocity": 80}]
    await t("create_clip", track_index=midi, clip_index=0, length=4, expect="4-beat")
    await t("set_clip_name", track_index=midi, clip_index=0, name="v2 chord", expect="v2 chord")
    await t("add_notes_to_clip", track_index=midi, clip_index=0, notes=notes, expect="Added 4")
    await t("replace_notes_in_clip", track_index=midi, clip_index=0,
            notes=notes + [{"pitch": 46, "start_time": 0.5, "duration": 0.25, "velocity": 70}],
            expect="holds 5 notes (4 removed)")
    await t("get_clip_key", track_index=midi, clip_index=0, expect='"best_key": "C major"')
    await t("delete_notes_from_clip", track_index=midi, clip_index=0, pitch=46,
            expect="Deleted 1 notes")
    await t("humanize_clip", track_index=midi, clip_index=0, timing_amount=0.01,
            velocity_amount=5, expect="Humanized 4")
    await t("transpose_notes", track_index=midi, clip_index=0, semitones=2, expect="+2")
    await t("get_clip_key", track_index=midi, clip_index=0, expect='"best_key": "D major"',
            note="after transposing by +2")
    await t("create_clip", track_index=midi, clip_index=1, length=4, note="clip for the pattern")
    await t("generate_euclidean_rhythm", steps=16, pulses=5, pitch=36, track_index=midi,
            clip_index=1, expect='"written_to_clip": true')
    await t("generate_automation_curve", curve_type="triangle", steps=9,
            expect=lambda s: len(json.loads(s)["points"]) == 9)
    await t("analyze_midi_session", max_tracks=first + 4, expect="v2 Test MIDI")
    await t("fire_clip", track_index=midi, clip_index=0, expect="Launched")
    await asyncio.sleep(0.6)
    await t("stop_clip", track_index=midi, clip_index=0, expect="Stop sent")
    await t("set_scene_tempo", scene_index=0, tempo=101, expect="101.00")
    await t("fire_scene", scene_index=0, expect="Launched scene 0")
    await asyncio.sleep(0.6)
    await t("stop_playback", expect="Stopped")
    await t("start_playback", expect="Playing")
    await asyncio.sleep(0.5)
    await t("get_master_analysis", expect="Master track")
    await t("stop_playback", expect="Stopped", note="second call")
    await t("undo", expect=lambda s: "Undone" in s or "Nothing undone" in s)
    await t("redo", expect=lambda s: "Redone" in s or "Nothing redone" in s)

    # -- browser and devices -------------------------------------------------
    await t("get_browser_tree", category_type="all", expect="Instruments")
    await t("get_browser_items_at_path", path="audio_effects", limit=10, expect="entries")
    uris = {}
    for label, path, name in (("eq", "audio_effects", "EQ Eight"),
                              ("compressor", "audio_effects", "Compressor"),
                              ("reverb", "audio_effects", "Reverb"),
                              ("limiter", "audio_effects", "Limiter"),
                              ("wavetable", "instruments", "Wavetable"),
                              ("drum_rack", "instruments", "Drum Rack")):
        uris[label] = await run.find_uri(path, name)
    print("uris:", uris, flush=True)
    if uris["wavetable"]:
        await t("load_instrument_or_effect", track_index=midi, uri=uris["wavetable"],
                expect="Wavetable")
    else:
        run.skip("load_instrument_or_effect", "Wavetable not found in the browser")
    chain = []
    if uris["compressor"] and uris["eq"]:
        await t("load_instrument_or_effect", track_index=audio, uri=uris["compressor"],
                expect="Compressor", note="audio effect onto an audio track")
        await t("load_instrument_or_effect", track_index=audio, uri=uris["eq"], expect="EQ Eight")
        text = await t("get_track_info", track_index=audio, note="to read the device chain",
                       expect='"devices"')
        chain = [d["name"] for d in json.loads(text)["devices"]]
    if "EQ Eight" in chain:
        eq_index = chain.index("EQ Eight")
        params = await t("get_device_parameters", track_index=audio, device_index=eq_index,
                         expect="EQ Eight")
        await t("set_eq_mode", track_index=audio, device_index=eq_index, mode=2, expect="M/S")
        await t("set_eq_mode", track_index=audio, device_index=eq_index, mode=0, expect="Stereo",
                note="back to Stereo")
        gain = re.search(r"\] (1 Gain A) = ", params)
        if gain:
            await t("set_device_parameter", track_index=audio, device_index=eq_index,
                    param_name="1 Gain A", value=3.0, expect="1 Gain A")
        else:
            run.skip("set_device_parameter", "EQ Eight has no parameter '1 Gain A' here")
    else:
        for name in ("get_device_parameters", "set_eq_mode", "set_device_parameter"):
            run.skip(name, "EQ Eight could not be loaded")
    if "Compressor" in chain:
        await t("set_sidechain_routing", target_track_index=audio,
                device_index=chain.index("Compressor"), source_track_index=midi,
                expect="input set to")
    else:
        run.skip("set_sidechain_routing", "Compressor could not be loaded")
    if uris["limiter"]:
        await t("load_device_on_master", uri=uris["limiter"], expect="Limiter")
        master = await t("get_device_parameters", use_master=True, device_index=0,
                         note="master chain", expect="parameters")
        position = 0 if "Limiter" in master.splitlines()[0] else None
        if position is not None:
            await t("delete_device", track_index=0, device_index=0, use_master=True,
                    expect="needs_confirmation", note="destructive tool without confirm: refused")
            await t("delete_device", track_index=0, device_index=0, use_master=True,
                    confirm=True, expect="Removed 'Limiter'")
            step = int((await t("list_ai_changes", limit=1, note="the deletion is in the journal",
                                expect="Deleted device 'Limiter'")).split("#", 1)[1].split(" ", 1)[0])
            await t("undo_ai_change", number=step, error_code="unsupported",
                    note="recorded only: Live's own undo is the way back")
        else:
            run.skip("delete_device", "Limiter is not the first master device; left untouched")
    else:
        run.skip("load_device_on_master", "Limiter not found in the browser")
        run.skip("delete_device", "nothing loaded to delete")
    if uris["reverb"] and returns:
        loaded = await t("load_device_on_return", return_index=0, uri=uris["reverb"],
                         expect="Reverb")
        count = len(re.search(r"Devices there now: (.*)\.", loaded).group(1).split(", ")) \
            if "Devices there now" in loaded else len(returns[0]["devices"]) + 1
        last = count - 1
        await t("set_return_device_parameter", return_index=0, device_index=last,
                param_name="Dry/Wet", value=0.5, expect="Dry/Wet")
        await t("delete_device", track_index=0, device_index=last, use_return=True,
                return_index=0, confirm=True, expect="Removed",
                note="remove the test reverb from Return A")
    else:
        run.skip("load_device_on_return", "Reverb or return track missing")
        run.skip("set_return_device_parameter", "Reverb or return track missing")
    if uris["drum_rack"]:
        await t("load_drum_kit", track_index=drums, rack_uri=uris["drum_rack"], kit_path="drums",
                expect="Drum Rack", note="kit_path 'drums': first loadable item of that folder")
    else:
        run.skip("load_drum_kit", "Drum Rack not found in the browser")
    await t("search_vst", name="e", expect=lambda s: "plug-in" in s.lower(),
            note="any installed plug-in with an 'e' in its name")

    # -- arrangement, warp, locators -----------------------------------------
    await t("set_warp_markers_batch", track_index="tempo", clip_index=0,
            markers=json.dumps([{"arr_clip_batch": [
                {"track": audio, "file_path": tone, "position": 0.0},
                {"track": audio2, "file_path": tone, "position": 0.0}]}]),
            expect='"succeeded": 2', note="keyword route: place the test tone on two audio tracks")
    await t("get_arrangement_clips", track_index=audio, expect="Arrangement clip")
    await t("set_clip_warp_mode", track_index=audio, clip_index=0, mode=4, expect="Complex")
    await t("get_warp_markers", track_index=audio, clip_index=0, expect="warp markers")
    await t("set_warp_marker", track_index=audio, clip_index=0, beat_time=4.0, sample_time=2.0,
            expect="Warp marker")
    await t("set_warp_markers_batch", track_index=str(audio), clip_index=0,
            markers=json.dumps([{"beat_time": 8.0, "sample_time": 4.0},
                                {"beat_time": 12.0, "sample_time": 6.0}]),
            expect="Set 2 of 2")
    await t("set_warp_markers_batch", track_index="warp_intel", clip_index=f"{audio}:0",
            markers=json.dumps([{"cmd": "analyze_drift", "grid_size": 1.0}]),
            expect='"cmd": "analyze_drift"', note="keyword route: warp_intel")
    await t("normalize_clip", track_index=audio, clip_index=0, arrangement=True, target_db=-1,
            expect="file peak -6.0", note="test tone peaks at -6.02 dBFS, so +5 dB gain")
    await t("create_locator", time=8, name="v2 A", expect="Created locator 'v2 A'")
    await t("create_locator", time=16, name="v2 B", expect="Created locator 'v2 B'")
    await t("get_locators", expect="v2 B")
    await t("delete_locator", index=0, expect="Deleted locator")
    await t("clear_locators", expect="needs_confirmation", note="without confirm: refused")
    await t("clear_locators", confirm=True, expect="0 left")

    # -- safety layer: confirmation, journal, single-step undo ----------------
    def step_of(answer: str) -> int:
        return int(answer.rsplit("Journal: #", 1)[1].split(" ", 1)[0])

    def session_now(answer: str) -> dict:
        return json.loads(answer)

    await t("get_safety_status", expect='"confirm_required_for_destructive": true')
    tempo_before = session_now(await t("get_session_info", note="before the journal checks",
                                       expect='"tempo"'))["tempo"]
    tempo_step = step_of(await t("set_tempo", tempo=117, expect="Journal: #"))
    name_step = step_of(await t("set_track_name", track_index=midi, name="v2 Journal",
                                expect="Journal: #"))
    await t("undo_ai_change", number=tempo_step, expect=f"Took back #{tempo_step}",
            note="takes back the tempo step only")
    await t("get_session_info", note="tempo is back, the later rename is still there",
            expect=lambda s: abs(session_now(s)["tempo"] - tempo_before) < 0.01
            and session_now(s)["tracks"][midi]["name"] == "v2 Journal")
    await t("undo_ai_change", number=tempo_step, error_code="busy",
            note="a step cannot be taken back twice")
    await t("undo_ai_change", number=name_step, expect="Took back",
            note="rename taken back")
    first_fader = step_of(await t("set_track_volume", track_index=midi, volume_db=-20,
                                  expect="-20.0 dB"))
    second_fader = step_of(await t("set_track_volume", track_index=midi, volume_db=-3,
                                   expect="-3.0 dB"))
    await t("undo_ai_change", number=first_fader, error_code="changed_since",
            note="the fader was moved again since: the older step is refused")
    await t("undo_ai_change", number=second_fader, expect="Took back")
    await t("get_track_info", track_index=midi, note="fader is back at -20 dB",
            expect=lambda s: abs(json.loads(s)["volume_db"] + 20.0) < 0.11)
    notes_step = step_of(await t("replace_notes_in_clip", track_index=midi, clip_index=0,
                                 notes=[{"pitch": 48, "start_time": 0, "duration": 1}],
                                 expect="holds 1 notes"))
    await t("undo_ai_change", number=notes_step, expect="Took back", note="notes restored")
    await t("get_clip_key", track_index=midi, clip_index=0, expect='"note_count": 4',
            note="the four notes are back")
    devices_before = len(json.loads(await t("get_track_info", track_index=audio2,
                                            note="device count before", expect='"devices"'))["devices"])
    if uris["compressor"]:
        load_step = step_of(await t("load_instrument_or_effect", track_index=audio2,
                                    uri=uris["compressor"], expect="Journal: #"))
        await t("undo_ai_change", number=load_step, expect="Took back",
                note="the loaded device is removed again")
        await t("get_track_info", track_index=audio2, note="device count after undo",
                expect=lambda s: len(json.loads(s)["devices"]) == devices_before)
    locator_step = step_of(await t("create_locator", time=32, name="v2 U", expect="Journal: #"))
    await t("undo_ai_change", number=locator_step, expect="Took back",
            note="the locator is deleted again")
    await t("get_locators", note="no locator left", expect=lambda s: "v2 U" not in s)
    marker_step = step_of(await t("set_warp_marker", track_index=audio, clip_index=0,
                                  beat_time=10.0, sample_time=5.0, expect="Journal: #"))
    markers_with = await t("get_warp_markers", track_index=audio, clip_index=0,
                           note="with the extra marker", expect="warp markers")
    await t("undo_ai_change", number=marker_step, expect="Took back",
            note="warp markers restored")
    await t("get_warp_markers", track_index=audio, clip_index=0, note="one marker fewer",
            expect=lambda s: len(s.splitlines()) == len(markers_with.splitlines()) - 1)
    count_before = session_now(await t("get_session_info", note="track count before",
                                       expect='"track_count"'))["track_count"]
    track_step = step_of(await t("create_midi_track", index=-1, expect="Journal: #"))
    await t("undo_ai_change", number=track_step, expect="Took back",
            note="the new track is deleted again")
    await t("get_session_info", note="track count after undo",
            expect=lambda s: session_now(s)["track_count"] == count_before)
    await t("list_ai_changes", limit=0, expect="[taken back]")

    # -- analyzer-dependent tools (synthetic frame) ---------------------------
    await t("apply_mastering_corrections", style="streaming", expect="No analyzer signal",
            note="without analyzer")
    run.send_analyzer_frame()
    await asyncio.sleep(0.3)
    synthetic = "synthetic analyzer frame sent by the test, not a real measurement"
    await t("get_master_analysis", expect="Analyzer (external measurement)", note=synthetic)
    await t("apply_mastering_corrections", style="streaming", expect="Gap to target: +3.5",
            note=synthetic)
    await t("suggest_mastering_chain", style="club", expect="Step 1", note=synthetic)
    await t("color_track_by_spectrum", track_index=midi, dry_run=False, expect="coloured",
            note=synthetic)
    await t("color_all_tracks_by_spectrum", dry_run=True, expect="Dry run", note=synthetic)

    # -- snapshot and .als tools ---------------------------------------------
    snap_dir = os.path.join(work, "snapshots")
    snap = await t("snapshot_session", label="v2test", snapshot_dir=snap_dir, confirm=True,
                   expect="Snapshot:")
    await t("list_snapshots", snapshot_dir=snap_dir, expect="snapshot(s)")
    match = re.search(r"Snapshot: (.*\.als)", snap)
    saved_ok = match and "did not change" not in snap and "could not save" not in snap
    if match and saved_ok:
        copy = os.path.join(work, "v2_als_edit.als")
        shutil.copy2(match.group(1), copy)
        await t("als_warp_read", als_path=copy, expect="v2 Test Audio")
        await t("als_warp_read", als_path=copy, track_name="v2 Test Audio", expect='"markers"',
                note="markers of one clip")
        await t("als_warp_write", als_path=copy, track_name="v2 Test Audio", backup=True,
                confirm=True,
                markers_json=json.dumps([{"sec_time": 0.0, "beat_time": 0.0},
                                         {"sec_time": 4.0, "beat_time": 8.0},
                                         {"sec_time": 8.0, "beat_time": 16.0}]),
                expect="Wrote 3 warp markers")
        await t("als_warp_derive", als_path=copy, source_track="v2 Test Audio",
                target_track="v2 Test Audio 2", offset_seconds=0.25, dry_run=True,
                expect="Dry run", note="dry run needs no confirm")
        await t("als_warp_derive", als_path=copy, source_track="v2 Test Audio",
                target_track="v2 Test Audio 2", offset_seconds=0.25, backup=False,
                confirm=True, expect="Wrote 3 markers")
        await t("als_warp_read", als_path=copy, track_name="v2 Test Audio 2",
                expect='"sec_time": 4.25', note="read back the derived markers")
        await t("set_tempo_automation", als_path=copy, backup=False, confirm=True,
                breakpoints=json.dumps([{"beat": 0, "bpm": 120}, {"beat": 16, "bpm": 90}]),
                expect='"events_written"')
        await t("set_tempo_automation", als_path=copy, breakpoints="[]", expect='"bpm": 90',
                note="read back")
        if uris["wavetable"]:
            await t("set_wavetable_mod_routing", als_path=copy, backup=False, confirm=True,
                    track_names=json.dumps(["v2 Test MIDI"]), expect='"patched_tracks": 1')
        else:
            run.skip("set_wavetable_mod_routing", "Wavetable was not loaded")
        run.edited_als = copy
    else:
        why = "the Set could not be saved to a known file (see snapshot_session)"
        for name in ("als_warp_read", "als_warp_write", "als_warp_derive",
                     "set_tempo_automation", "set_wavetable_mod_routing"):
            run.skip(name, why)

    # -- grouping last: it changes track indices ------------------------------
    text = await t("group_tracks", track_indices=[audio, audio2], verdict_on_error=LIMIT,
                   note="types Shift+Right and Ctrl+G into Live's window")
    if not text.startswith("Grouped"):
        run.rows[-1]["verdict"] = LIMIT
    await t("get_session_info", note="after grouping",
            expect=lambda s: any(row["kind"] == "group" for row in json.loads(s)["tracks"])
            or not text.startswith("Grouped"))
    await t("set_tempo", tempo=original_tempo, note="restore the tempo", expect="Tempo is now")


def scrubber(work_dir: str):
    """Returns a function that removes machine-specific paths from text."""
    swaps = []
    for path, label in ((os.path.abspath(work_dir), "<work>"),
                        (os.path.expanduser("~"), "%USERPROFILE%")):
        for variant in {path, path.replace("\\", "/"), path.replace("/", "\\"),
                        path.replace("\\", "\\\\")}:
            swaps.append((variant, label))
    swaps.sort(key=lambda pair: -len(pair[0]))

    def scrub(text: str) -> str:
        for variant, label in swaps:
            text = re.sub(re.escape(variant), lambda _m: label, text, flags=re.IGNORECASE)
        return text

    return scrub


def protocol(run: Run, all_tools, started: str, status: dict) -> str:
    never = sorted(set(all_tools) - run.called)
    by_verdict = {}
    for row in run.rows:
        by_verdict[row["verdict"]] = by_verdict.get(row["verdict"], 0) + 1
    worst = {}
    order = {FAIL: 0, LIMIT: 1, SKIP: 2, PASS: 3}
    for row in run.rows:
        current = worst.get(row["tool"])
        if current is None or order[row["verdict"]] < order[current]:
            worst[row["tool"]] = row["verdict"]
    out = [
        "# Live test protocol",
        "",
        f"Run on {started} against Ableton Live {status.get('live_version')} "
        f"(Python {status.get('python')}), bridge {status.get('bridge_version')}, "
        f"source hash `{status.get('file_hash')}`, {status.get('command_count')} commands.",
        "",
        "Produced by `tests/live_protocol.py`: the MCP server runs as a child process and "
        "every tool is called through the MCP protocol, as an assistant would.",
        "",
        "## Summary",
        "",
        f"- Tools offered by the server: {len(all_tools)}",
        f"- Tools called: {len(run.called & set(all_tools))}",
        f"- Calls made: {len(run.rows)} "
        f"({', '.join(f'{count} {verdict}' for verdict, count in sorted(by_verdict.items()))})",
        f"- Tools never called: {', '.join(never) if never else 'none'}",
        "",
        "Verdicts: **pass** = answered as expected; **limit** = works as far as Live's API "
        "or the environment allows, see note; **skipped** = precondition missing; "
        "**FAIL** = wrong or error answer.",
        "",
        "## Result per tool",
        "",
        "| Tool | Verdict | Calls |",
        "|---|---|---:|",
    ]
    for name in sorted(all_tools):
        calls = sum(1 for row in run.rows if row["tool"] == name)
        out.append(f"| `{name}` | {worst.get(name, 'not called')} | {calls} |")
    out += ["", "## Every call", "",
            "| # | Tool | Arguments | Verdict | ms | Answer (first line) | Note |",
            "|---:|---|---|---|---:|---|---|"]
    for number, row in enumerate(run.rows, 1):
        arguments = json.dumps(row["args"], ensure_ascii=False)
        if len(arguments) > 70:
            arguments = arguments[:67] + "..."
        first_line = (row["answer"].strip().splitlines() or [""])[0]
        if len(first_line) > 90:
            first_line = first_line[:87] + "..."
        scrub = scrubber(run.work)
        clean = lambda text: scrub(text).replace("|", "\\|")
        out.append(f"| {number} | `{row['tool']}` | `{clean(arguments)}` | {row['verdict']} | "
                   f"{row['ms']} | {clean(first_line)} | {clean(row['note'])} |")
    out.append("")
    return "\n".join(out)


async def main_async(args) -> int:
    os.makedirs(args.work_dir, exist_ok=True)
    analyzer_port = free_udp_port()
    environment = dict(os.environ, ABLETON_MCP_ANALYZER_PORT=str(analyzer_port),
                       ABLETON_MCP_LOG_LEVEL="WARNING")
    server = StdioServerParameters(command=sys.executable,
                                   args=[os.path.join(ROOT, "MCP_Server", "server.py")],
                                   env=environment)
    started = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            all_tools = [tool.name for tool in (await session.list_tools()).tools]
            run = Run(session, args.work_dir, analyzer_port)
            run.edited_als = None
            try:
                await scenario(run)
            except Exception as problem:
                import traceback
                traceback.print_exc()
                run.rows.append({"tool": "(scenario)", "args": {}, "verdict": FAIL, "ms": 0,
                                 "note": "the test script itself stopped here",
                                 "answer": repr(problem)})
            status_text = await session.call_tool("bridge_status", {})
            try:
                status = json.loads(status_text.content[0].text)
            except Exception:
                status = {}
    report = protocol(run, all_tools, started, status)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(report)
    with open(os.path.join(args.work_dir, "live_protocol_raw.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"rows": run.rows, "edited_als": run.edited_als}, handle, indent=1,
                  ensure_ascii=False)
    failed = sum(1 for row in run.rows if row["verdict"] == FAIL)
    print(f"\n{len(run.rows)} calls, {failed} failed; protocol: {args.out}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--out", default=os.path.join(ROOT, "docs", "LIVE_TEST_PROTOCOL.md"))
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
