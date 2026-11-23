# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""End-to-end tests without Ableton Live.

The Remote Script runs against the fake object model from fake_live.py, with
a thread standing in for Live's display timer. Requests travel over a real
TCP socket through the same client code the MCP server uses, so framing,
the main-thread gate, the register and the handlers are all exercised.

Run:  python -m unittest discover -s tests -v
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


PORT = _free_port()
os.environ["ABLETON_MCP_PORT"] = str(PORT)
os.environ["ABLETON_MCP_EDIT_RATE"] = "0"  # no pacing in tests
os.environ["ABLETON_MCP_ANALYZER_PORT"] = str(_free_port())
JOURNAL_DIR = tempfile.mkdtemp(prefix="bridge_journal_")
os.environ["ABLETON_MCP_JOURNAL_DIR"] = JOURNAL_DIR
os.environ.pop("ABLETON_MCP_CONFIRM", None)
os.environ.pop("ABLETON_MCP_MAX_ZONE", None)

import fake_live  # noqa: E402

SONG, APP = fake_live.install()

import AbletonMCP_Remote_Script as script  # noqa: E402
from MCP_Server import core  # noqa: E402
from MCP_Server.link import LiveError, LiveLink  # noqa: E402
from MCP_Server import tools  # noqa: E402,F401
from MCP_Server.tools import (  # noqa: E402
    arrangement, clips, devices, mastering, safety, session, tracks,
)


class BridgeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.surface = script.create_instance(None)
        cls.pumping = True

        def pump():
            while cls.pumping:
                cls.surface.update_display()
                time.sleep(0.005)

        cls.pump = threading.Thread(target=pump, daemon=True)
        cls.pump.start()
        deadline = time.time() + 5
        while not cls.surface.listener.bound and time.time() < deadline:
            time.sleep(0.02)
        cls.link = LiveLink("127.0.0.1", PORT)

    @classmethod
    def tearDownClass(cls):
        cls.link.close()
        core.live.close()
        cls.surface.disconnect()
        cls.pumping = False

    def call(self, command, **params):
        return self.link.call(command, **params)

    def confirmed(self, command, **params):
        """Send a destructive command the way a client does after the user agreed."""
        self.link.confirmed = True
        try:
            return self.link.call(command, **params)
        finally:
            self.link.confirmed = False


class WireTests(BridgeCase):
    def test_register_is_served(self):
        commands = self.link.commands()
        self.assertGreater(len(commands), 60)
        self.assertEqual(commands["get_session_info"]["zone"], "read")
        self.assertEqual(commands["delete_device"]["zone"], "destructive")

    def test_unknown_command(self):
        with self.assertRaises(LiveError) as caught:
            self.call("no_such_thing")
        self.assertEqual(caught.exception.code, "unknown_command")

    def test_bad_parameter_type(self):
        with self.assertRaises(LiveError) as caught:
            self.call("set_tempo", tempo="fast")
        self.assertEqual(caught.exception.code, "bad_params")

    def test_string_numbers_are_accepted(self):
        self.assertEqual(self.call("get_track_info", track_index="1")["name"], "Bass")

    def test_split_and_joined_messages(self):
        raw = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        one = json.dumps({"type": "get_version", "params": {}}).encode()
        raw.sendall(one[:7])
        time.sleep(0.05)
        raw.sendall(one[7:] + b"\n" + one)  # rest of first, newline, a second one
        decoder, text, replies = json.JSONDecoder(), "", []
        while len(replies) < 2:
            text += raw.recv(65536).decode()
            while text.strip():
                try:
                    reply, end = decoder.raw_decode(text.lstrip())
                except ValueError:
                    break
                replies.append(reply)
                text = text.lstrip()[end:]
        raw.close()
        self.assertTrue(all(r["status"] == "success" for r in replies))

    def test_legacy_error_shape(self):
        raw = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        raw.sendall(json.dumps({"type": "get_track_info", "params": {"track_index": 99}}).encode())
        reply = json.loads(raw.recv(65536).decode())
        raw.close()
        self.assertEqual(reply["status"], "error")
        self.assertIn("message", reply)

    def test_hot_reload_keeps_working(self):
        before = self.call("get_version")
        result = self.call("hot_reload")
        self.assertEqual(result["hot_reload"], "ok")
        self.assertEqual(result["commands"], before["command_count"])
        self.assertEqual(self.call("get_version")["reload_count"], before["reload_count"] + 1)

    def test_hot_reload_with_broken_module_keeps_old_handlers(self):
        broken = os.path.join(ROOT, "AbletonMCP_Remote_Script", "handlers", "zz_broken.py")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("def oops(:\n    pass\n")
        try:
            result = self.call("hot_reload")
        finally:
            os.remove(broken)
        self.assertEqual(result["hot_reload"], "error")
        self.assertTrue(result["kept_previous"])
        self.assertIn("syntax error", result["reason"])
        self.assertEqual(self.call("get_track_info", track_index=0)["name"], SONG.tracks[0].name)
        self.assertEqual(self.call("hot_reload")["hot_reload"], "ok")

    def test_deferred_result_is_read_on_a_later_tick(self):
        result = self.call("jump_to_time", time=12.0)
        self.assertEqual(result["time"], 12.0)
        self.call("jump_to_time", time=0.0)

    def test_eval_is_off_by_default(self):
        with self.assertRaises(LiveError) as caught:
            self.confirmed("eval_code", code="1+1")
        self.assertEqual(caught.exception.code, "disabled")


class CommandTests(BridgeCase):
    def test_every_registered_command_has_metadata(self):
        for name, entry in self.link.commands().items():
            self.assertIn(entry["zone"], ("read", "reversible", "destructive"), name)
            self.assertTrue(entry["summary"], name)

    def test_session_overview(self):
        info = self.call("get_session_info")
        self.assertEqual(info["track_count"], len(SONG.tracks))
        self.assertEqual(info["tracks"][0]["kind"], "midi")

    def test_volume_in_db_uses_display(self):
        result = self.call("set_track_volume", track_index=0, volume_db=-6.0)
        self.assertEqual(result["display"], "-6.0 dB")
        self.assertAlmostEqual(SONG.tracks[0].mixer_device.volume.value, 0.70, places=2)
        result = self.call("set_track_volume", track_index=0, volume_db="-inf")
        self.assertEqual(SONG.tracks[0].mixer_device.volume.value, 0.0)

    def test_notes_round_trip(self):
        notes = [{"pitch": 36, "start_time": 0, "duration": 0.25, "velocity": 100},
                 {"pitch": 42, "start": 0.5, "dur": 0.25, "vel": 70}]
        self.call("create_clip", track_index=2, clip_index=0, length=4)
        self.assertEqual(self.call("replace_notes_in_clip", track_index=2, clip_index=0,
                                   notes=notes)["written"], 2)
        back = self.call("get_clip_notes", track_index=2, clip_index=0)["notes"]
        self.assertEqual([n["pitch"] for n in back], [36, 42])
        self.assertEqual(back[1]["start_time"], 0.5)
        self.call("add_notes_to_clip", track_index=2, clip_index=0,
                  notes=json.dumps([{"pitch": 46, "start_time": 1}]))
        deleted = self.call("delete_notes_from_clip", track_index=2, clip_index=0, pitch=46)
        self.assertEqual(deleted["deleted"], 1)
        self.call("transpose_notes", track_index=2, clip_index=0, semitones=12)
        self.call("humanize_clip", track_index=2, clip_index=0, seed=1)
        with self.assertRaises(LiveError):
            self.call("transpose_notes", track_index=2, clip_index=0, semitones=100)

    def test_wrong_clip_kind(self):
        with self.assertRaises(LiveError) as caught:
            self.call("get_clip_notes", track_index=1, clip_index=0)
        self.assertEqual(caught.exception.code, "wrong_kind")

    def test_devices(self):
        listing = self.call("get_device_parameters", track_index=1, device_index=0)
        self.assertEqual(listing["device"], "Compressor")
        self.call("set_device_parameter", track_index=1, device_index=0,
                  param_name="threshold", value=0.25)
        self.assertEqual(SONG.tracks[1].devices[0].parameters[1].value, 0.25)
        with self.assertRaises(LiveError):
            self.call("set_device_parameter", track_index=1, device_index=0,
                      param_name="Threshold", value=7)
        self.assertEqual(self.call("set_eq_mode", track_index=1, device_index=1,
                                   mode=2)["mode_name"], "M/S")
        routed = self.call("set_sidechain_routing", target_track_index=1, device_index=0,
                           source_track_index=0)
        self.assertTrue(routed["routing_set"])
        self.assertEqual(routed["set_to"], "1-Drums")

    def test_browser_and_loading(self):
        tree = self.call("get_browser_tree")
        self.assertIn("instruments", tree["available_categories"])
        folder = self.call("get_browser_items_at_path", path="Audio Effects")
        self.assertEqual(folder["total_count"], 2)
        loaded = self.call("load_browser_item", track_index=2, item_uri="query:AudioFx#Reverb")
        self.assertEqual(loaded["new_devices"], ["Reverb"])
        hits = self.call("search_vst", name="pro-q")
        self.assertEqual(hits["results"][0]["uri"], "query:Plugins#VST3:FabFilter:Pro-Q%203")
        with self.assertRaises(LiveError):
            self.call("load_browser_item", track_index=2, item_uri="query:Nope#Nothing")

    def test_locators(self):
        self.call("create_locator", time=8.0, name="Verse")
        self.call("create_locator", time=4.0, name="Intro")
        rows = self.call("get_locators")["locators"]
        self.assertEqual([r["name"] for r in rows], ["Intro", "Verse"])
        self.call("delete_locator", index=0)
        self.assertEqual(self.confirmed("clear_locators")["remaining"], 0)
        SONG.is_playing = True
        with self.assertRaises(LiveError):
            self.call("create_locator", time=1.0)
        SONG.is_playing = False

    def test_warp(self):
        self.call("set_warp_marker", track_index=1, clip_index=0, beat_time=8.0, sample_time=4.1)
        batch = self.call("set_warp_markers_batch", track_index=1, clip_index=0,
                          markers=[{"beat_time": 12.0, "sample_time": 6.2}])
        self.assertEqual(batch["markers_set"], 1)
        drift = self.call("warp_intel", track_index=1, clip_index=0,
                          operation={"cmd": "analyze_drift"})
        self.assertEqual(drift["count"], 4)
        moved = self.call("set_warp_markers_batch", track_index="warp_intel", clip_index="1:0",
                          markers=[{"cmd": "find_nearest", "beat_time": 7.9}])
        self.assertEqual(moved["marker"]["beat_time"], 8.0)

    def test_legacy_keywords(self):
        version = self.call("set_warp_markers_batch", track_index="version", clip_index=0,
                            markers=[])
        self.assertIn("file_hash", version)
        reload_reply = self.call("set_warp_markers_batch", track_index="reload", clip_index=0,
                                 markers=[])
        self.assertEqual(reload_reply["hot_reload"], "ok")

    def test_tempo_follow(self):
        self.call("set_tempo_follow", breakpoints=[{"beat": 0, "bpm": 100}, {"beat": 16, "bpm": 140}])
        SONG.current_song_time = 20.0
        time.sleep(0.1)
        self.assertEqual(SONG.tempo, 140.0)
        self.call("set_tempo_follow", breakpoints=[])
        SONG.current_song_time = 0.0


class SafetyTests(BridgeCase):
    """Confirmation of destructive commands, the journal and single-step undo."""

    def last_number(self):
        return self.call("list_changes", limit=1)["entries"][-1]["n"]

    def test_destructive_command_needs_confirm(self):
        with self.assertRaises(LiveError) as caught:
            self.call("delete_track", track_index=0)
        self.assertEqual(caught.exception.code, "needs_confirmation")
        with self.assertRaises(LiveError) as caught:
            self.call("set_warp_markers_batch", track_index="del:0", clip_index=0, markers=[])
        self.assertEqual(caught.exception.code, "needs_confirmation")

    def test_every_change_gets_a_number(self):
        first = self.call("set_tempo", tempo=111)["journal"][0]
        second = self.call("set_track_mute", track_index=0, mute=True)["journal"][0]
        self.assertEqual(second["n"], first["n"] + 1)
        self.assertEqual(first["undo"], "exact")
        self.assertIn("Tempo", first["text"])
        self.assertNotIn("journal", self.call("get_session_info"))
        self.assertNotIn("journal", self.call("start_playback"))
        self.call("stop_playback")
        self.call("set_track_mute", track_index=0, mute=False)

    def test_single_step_undo_leaves_other_steps_alone(self):
        before = SONG.tempo
        tempo_step = self.call("set_tempo", tempo=97)["journal"][0]["n"]
        self.call("set_track_name", track_index=2, name="Renamed later")
        result = self.call("undo_change", n=tempo_step)
        self.assertEqual(result["undone"], tempo_step)
        self.assertEqual(SONG.tempo, before)
        self.assertEqual(SONG.tracks[2].name, "Renamed later")   # the later step stays
        with self.assertRaises(LiveError) as caught:
            self.call("undo_change", n=tempo_step)               # not twice
        self.assertEqual(caught.exception.code, "busy")

    def test_undo_refuses_if_the_user_changed_it_since(self):
        step = self.call("set_track_volume", track_index=0, volume_db=-9)["journal"][0]["n"]
        SONG.tracks[0].mixer_device.volume.value = 0.33          # the user moved the fader
        with self.assertRaises(LiveError) as caught:
            self.call("undo_change", n=step)
        self.assertEqual(caught.exception.code, "changed_since")
        self.assertEqual(SONG.tracks[0].mixer_device.volume.value, 0.33)

    def test_undo_of_notes_tracks_devices_and_locators(self):
        self.call("create_midi_track", index=-1)
        track_step = self.last_number()
        index = len(SONG.tracks) - 1
        self.call("create_clip", track_index=index, clip_index=0, length=4)
        self.call("replace_notes_in_clip", track_index=index, clip_index=0,
                  notes=[{"pitch": 60, "start_time": 0}, {"pitch": 62, "start_time": 1}])
        self.call("transpose_notes", track_index=index, clip_index=0, semitones=5)
        transpose_step = self.last_number()
        self.call("undo_change", n=transpose_step)
        pitches = [n["pitch"] for n in self.call("get_clip_notes", track_index=index,
                                                 clip_index=0)["notes"]]
        self.assertEqual(pitches, [60, 62])

        devices_before = len(SONG.tracks[index].devices)
        self.call("load_browser_item", track_index=index, item_uri="query:AudioFx#Reverb")
        load_step = self.last_number()
        self.call("undo_change", n=load_step)
        self.assertEqual(len(SONG.tracks[index].devices), devices_before)

        self.call("create_locator", time=24.0, name="Bridge")
        locator_step = self.last_number()
        self.call("undo_change", n=locator_step)
        self.assertEqual([c for c in SONG.cue_points if c.time == 24.0], [])

        count = len(SONG.tracks)
        self.call("undo_change", n=track_step)                   # the track goes, clip and all
        self.assertEqual(len(SONG.tracks), count - 1)

    def test_recorded_only_steps_say_so(self):
        self.call("load_browser_item", track_index=2, item_uri="query:AudioFx#Limiter")
        last = len(SONG.tracks[2].devices) - 1
        self.confirmed("delete_device", track_index=2, device_index=last)
        step = self.last_number()
        with self.assertRaises(LiveError) as caught:
            self.call("undo_change", n=step)
        self.assertEqual(caught.exception.code, "unsupported")
        self.assertIn("Live's own undo", str(caught.exception))

    def test_journal_file_is_written(self):
        self.call("set_tempo", tempo=122)
        path = self.call("list_changes")["journal_file"]
        self.assertTrue(path.startswith(JOURNAL_DIR))
        with open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.assertTrue(any("Tempo" in row.get("text", "") for row in rows))

    def test_safety_tools(self):
        text = tracks.set_track_name(2, "Journal test")
        self.assertIn("Journal: #", text)
        number = int(text.rsplit("#", 1)[1].split(" ", 1)[0])
        self.assertIn(f"#{number} ", safety.list_ai_changes())
        self.assertIn(f"Took back #{number}", safety.undo_ai_change(number))
        self.assertIn("[taken back]", safety.list_ai_changes())
        mute_text = tracks.set_track_mute(0, True)
        mute_number = int(mute_text.rsplit("#", 1)[1].split(" ", 1)[0])
        SONG.tracks[0].mute = False                              # the user un-muted it
        self.assertIn("changed_since", safety.undo_ai_change(mute_number))
        status = json.loads(safety.get_safety_status())
        self.assertIn("delete_device", status["destructive_tools_need_confirm"])
        self.assertTrue(status["bridge"]["confirm_required_for_destructive"])

    def test_zone_limit(self):
        os.environ["ABLETON_MCP_MAX_ZONE"] = "read"
        try:
            self.assertIn("zone_not_allowed", tracks.set_track_name(2, "Nope"))
            self.assertFalse(session.get_session_info().startswith("Not executed"))
        finally:
            os.environ.pop("ABLETON_MCP_MAX_ZONE")


class ToolTests(BridgeCase):
    """Every MCP tool that needs Live is called once through its wrapper."""

    def ok(self, text):
        self.assertIsInstance(text, str)
        self.assertFalse(text.startswith("Error"), text)
        return text

    def test_tool_count(self):
        self.assertEqual(len(core.TOOLS), 80)

    def test_session_tools(self):
        self.ok(session.get_session_info())
        self.ok(session.set_tempo("128"))
        self.ok(session.start_playback())
        self.ok(session.stop_playback())
        self.ok(session.undo())
        self.ok(session.redo())
        self.ok(session.set_arrangement_record("false"))
        self.ok(session.fire_scene(1))
        self.ok(session.set_scene_tempo(0, 90))
        self.ok(session.switch_view("Arranger"))
        self.ok(session.focus_view("Session"))
        self.ok(session.jump_to_time("16"))
        self.ok(session.set_arrangement_loop(8, 16, True))
        self.ok(session.bridge_status())
        self.ok(session.hot_reload())

    def test_track_tools(self):
        self.ok(tracks.get_track_info(0))
        self.ok(tracks.create_midi_track())
        self.ok(tracks.create_audio_track(-1))
        self.ok(tracks.set_track_name(2, "Keys 2"))
        self.assertIn("-3.0 dB", self.ok(tracks.set_track_volume(1, -3)))
        self.ok(tracks.set_track_mute(1, "true"))
        self.ok(tracks.set_track_color(1, 12))
        self.ok(tracks.set_track_send(1, 0, 0.3))
        self.ok(tracks.select_tracks("[0, 1]"))
        self.ok(tracks.freeze_track(1))
        self.ok(tracks.get_return_tracks())
        self.ok(tracks.set_return_track_volume(0, 0.5))

    def test_clip_tools(self):
        self.ok(clips.create_clip(2, 1, 8))
        self.ok(clips.set_clip_name(2, 1, "New"))
        self.ok(clips.replace_notes_in_clip(2, 1, [{"pitch": 60, "start_time": 0}]))
        self.ok(clips.add_notes_to_clip(2, 1, '[{"pitch": 64, "start_time": 1}]'))
        self.ok(clips.fire_clip(2, 1))
        self.ok(clips.stop_clip(2, 1))
        self.ok(clips.humanize_clip(2, 1))
        self.ok(clips.transpose_notes(2, 1, -2))
        self.ok(clips.delete_notes_from_clip(2, 1, pitch=62))
        self.assertIn("best_key", self.ok(clips.get_clip_key(0, 0)))
        self.ok(clips.analyze_midi_session())
        pattern = json.loads(self.ok(clips.generate_euclidean_rhythm(8, 3, 36)))
        self.assertEqual(pattern["pattern"], [1, 0, 0, 1, 0, 0, 1, 0])
        self.ok(clips.generate_euclidean_rhythm(16, 4, 36, track_index=2, clip_index=1))
        curve = json.loads(self.ok(clips.generate_automation_curve("sine", 5)))
        self.assertEqual([p["value"] for p in curve["points"]], [0.0, 0.5, 1.0, 0.5, 0.0])
        self.assertTrue(clips.generate_automation_curve("wobble", 5).startswith("Error"))

    def test_device_tools(self):
        self.ok(devices.get_device_parameters(1, 0))
        self.ok(devices.set_device_parameter(1, 0, "Threshold", 0.4))
        self.ok(devices.set_return_device_parameter(0, 0, "Threshold", 0.4))
        self.ok(devices.set_eq_mode(1, 1, 1))
        self.ok(devices.set_sidechain_routing(1, 0, 0))
        self.ok(devices.load_instrument_or_effect(2, "query:Synths#Operator"))
        self.ok(devices.load_device_on_master("query:AudioFx#Limiter"))
        self.ok(devices.load_device_on_return(1, "query:AudioFx#Reverb"))
        self.ok(devices.load_drum_kit(2, "query:Synths#Operator", "drums/acoustic"))
        self.ok(devices.search_vst("Pro-Q"))
        self.ok(devices.get_browser_tree())
        self.ok(devices.get_browser_items_at_path("plugins/VST3", 1))
        self.assertIn("Available here", devices.get_browser_items_at_path("plugins/nope"))
        count = len(SONG.master_track.devices)
        self.assertIn("needs_confirmation",
                      devices.delete_device(0, count - 1, use_master=True))
        self.assertEqual(len(SONG.master_track.devices), count)
        self.ok(devices.delete_device(0, count - 1, use_master=True, confirm=True))
        self.assertEqual(len(SONG.master_track.devices), count - 1)

    def test_arrangement_tools(self):
        self.ok(arrangement.get_arrangement_clips(1))
        self.ok(arrangement.set_clip_warp_mode(1, 0, 5))
        self.assertEqual(SONG.tracks[1].arrangement_clips[0].warp_mode, 6)
        self.ok(arrangement.get_warp_markers(1, 0))
        self.ok(arrangement.set_warp_marker(1, 0, 16, 8.3))
        self.ok(arrangement.set_warp_markers_batch("1", 0, '[{"beat_time": 20, "sample_time": 10.2}]'))
        self.ok(arrangement.set_warp_markers_batch("version", 0, "[]"))
        self.ok(arrangement.create_locator(32, "Outro"))
        self.ok(arrangement.get_locators())
        self.ok(arrangement.delete_locator(0))
        self.assertIn("needs_confirmation", arrangement.clear_locators())
        self.ok(arrangement.clear_locators(confirm="true"))

    def test_mastering_tools_without_analyzer(self):
        self.ok(mastering.get_master_analysis())
        self.ok(mastering.apply_mastering_corrections())
        self.ok(mastering.suggest_mastering_chain("club"))
        self.assertTrue(mastering.color_track_by_spectrum(0).startswith("Error"))

    def test_mastering_tools_with_analyzer(self):
        frame = {"lufs_approx": -18.0, "peak_db": -3.0, "rms_db": -20.0,
                 "bands": {"sub": -20, "low": -30, "mid": -40, "high": -35, "air": -999}}
        with core.analyzer._lock:
            core.analyzer._frame, core.analyzer._stamp = frame, time.time()
        self.assertIn("sub", self.ok(mastering.get_master_analysis()))
        self.assertIn("+4.0", self.ok(mastering.apply_mastering_corrections()))
        self.ok(mastering.suggest_mastering_chain())
        self.ok(mastering.color_track_by_spectrum(0))
        self.assertEqual(SONG.tracks[0].color, 0x1A3CFF)
        self.ok(mastering.color_all_tracks_by_spectrum(dry_run=True))
        with core.analyzer._lock:
            core.analyzer._frame = {}

    def test_track_meters_sample_every_track(self):
        result = self.call("get_track_meters", seconds=0.3)
        self.assertTrue(1 <= result["samples"] <= 8, result["samples"])  # at most one reading per 50 ms
        kinds = [row["kind"] for row in result["tracks"]]
        self.assertEqual(kinds.count("track"), len(SONG.tracks))
        self.assertEqual(kinds.count("return"), len(SONG.return_tracks))
        self.assertEqual(kinds[-1], "master")
        first = result["tracks"][0]
        self.assertEqual(first["meter_peak"], 0.5)  # max of the fake meters 0.5 / 0.25
        self.assertEqual(first["meter_mean"], 0.5)
        self.assertEqual(first["peak_db"], -32.0)  # 76 * 0.5 - 70 (fake has no output_meter_level)
        without = self.call("get_track_meters", seconds=0, include_returns=False)
        self.assertNotIn("return", [row["kind"] for row in without["tracks"]])

    def test_track_levels_with_y_meter_frame(self):
        name = SONG.tracks[0].name
        core.analyzer.accept(_osc("/ytrack", name, 0.1, 0.5, 0.05, 0.02, 0.01, 0.005, 0.0))
        text = self.ok(mastering.get_track_levels(0.2))
        self.assertIn("Y Meter: RMS -20.0 dB, peak -6.0 dBFS", text)
        self.assertIn("sub -26", text)
        self.assertNotIn("air", text.split("Y Meter")[1].split("\n")[0])  # silent band left out
        with core.analyzer._lock:
            core.analyzer._tracks.clear()
        self.assertIn("put the \"Y Meter\"", self.ok(mastering.get_track_levels(0)))
        self.assertTrue(mastering.get_track_levels(11).startswith("Error"))


def _osc(address, *values):
    """Encode one OSC message the way Max's udpsend does."""
    import struct

    def pad(raw):
        raw += b"\0"
        return raw + b"\0" * (-len(raw) % 4)

    tags, body = ",", b""
    for value in values:
        if isinstance(value, str):
            tags += "s"
            body += pad(value.encode("utf-8"))
        else:
            tags += "f"
            body += struct.pack(">f", value)
    return pad(address.encode("utf-8")) + pad(tags.encode("ascii")) + body


class AnalyzerFeedTests(unittest.TestCase):
    def test_json_master_frame(self):
        from MCP_Server.analyzer_feed import AnalyzerFeed
        feed = AnalyzerFeed(port=1)
        feed.accept(json.dumps({"rms_db": -20.0}).encode("utf-8"))
        self.assertEqual(feed.fresh()["rms_db"], -20.0)

    def test_json_wrapped_in_osc_address(self):
        from MCP_Server.analyzer_feed import AnalyzerFeed
        feed = AnalyzerFeed(port=1)
        feed.accept(_osc(json.dumps({"peak_db": -3.0})))
        self.assertEqual(feed.fresh()["peak_db"], -3.0)

    def test_track_frame_and_garbage(self):
        from MCP_Server.analyzer_feed import AnalyzerFeed
        feed = AnalyzerFeed(port=1)
        feed.accept(_osc("/ytrack", "Bass Line", 1.0, 1.0, 0, 0, 0, 0, 0))
        feed.accept(b"\xff\x00 not a frame")
        feed.accept(_osc("/ytrack", "short", 1.0))
        frame = feed.tracks()["Bass Line"]
        self.assertEqual(frame["rms_db"], 0.0)
        self.assertEqual(frame["bands"]["sub"], -999.0)
        self.assertNotIn("short", feed.tracks())
        self.assertEqual(feed.tracks(max_age=-1), {})

    def test_several_servers_share_the_port(self):
        from MCP_Server.analyzer_feed import AnalyzerFeed

        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        def wait(condition, seconds=3.0):
            end = time.time() + seconds
            while time.time() < end:
                if condition():
                    return True
                time.sleep(0.02)
            return False

        def send(name):
            out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            out.sendto(_osc("/ytrack", name, 1.0, 1.0, 0, 0, 0, 0, 0), ("127.0.0.1", port))
            out.close()

        first, second, third = (AnalyzerFeed(port=port) for _ in range(3))
        for feed in (first, second, third):
            feed.renew_s, feed.poll_s = 0.2, 0.05
        try:
            first.start()
            self.assertTrue(wait(lambda: first.role == "hub"))
            second.start()
            third.start()
            self.assertTrue(wait(lambda: second.role == third.role == "relayed"
                                 and first.subscribers == 2))
            self.assertTrue(wait(lambda: (send("One") or True)
                                 and all("One" in f.tracks() for f in (first, second, third))))
            first.stop()  # the owner ends: one of the others takes the port over
            self.assertTrue(wait(lambda: "hub" in (second.role, third.role)))
            self.assertTrue(wait(lambda: (send("Two") or True)
                                 and all("Two" in f.tracks() for f in (second, third))))
        finally:
            for feed in (first, second, third):
                feed.stop()



class StrictJsonTests(unittest.TestCase):
    def test_infinity_becomes_null(self):
        from MCP_Server.core import strict_json
        text = json.dumps(strict_json({"volume_db": float("-inf"), "x": [float("nan"), 1.5]}),
                          allow_nan=False)
        self.assertEqual(json.loads(text), {"volume_db": None, "x": [None, 1.5]})

if __name__ == "__main__":
    unittest.main()
