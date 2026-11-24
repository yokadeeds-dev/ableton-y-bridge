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
        # the journal summary of a read is no list of journal steps
        self.assertNotIn("journal", status, status.get("journal"))
        self.assertIn("entries", status["bridge"]["journal"])

    def test_zone_limit(self):
        os.environ["ABLETON_MCP_MAX_ZONE"] = "read"
        try:
            self.assertIn("zone_not_allowed", tracks.set_track_name(2, "Nope"))
            self.assertFalse(session.get_session_info().startswith("Not executed"))
        finally:
            os.environ.pop("ABLETON_MCP_MAX_ZONE")


class TimeoutAndJournalTests(BridgeCase):
    """PTc 2026-11-24: a timeout must not lose a change; journal and meters stay sound."""

    def patched(self, name, timeout, handler):
        spec = self.surface._hub.registry.get(name)
        kept = (spec.timeout, spec.handler)
        spec.timeout, spec.handler = timeout, handler(spec.handler)
        self.addCleanup(lambda: setattr(spec, "timeout", kept[0]) or setattr(spec, "handler", kept[1]))
        return spec

    def texts(self):
        return [e["text"] for e in self.call("list_changes", limit=0)["entries"]]

    def wait_for(self, check, seconds=5.0):
        """Poll instead of fixed sleeps: a busy machine must not make tests flaky."""
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(0.05)
        return check()

    def undo_last(self, count):
        for entry in self.call("list_changes", limit=count)["entries"][::-1]:
            self.call("undo_change", n=entry["n"])

    def test_timeout_while_running_is_still_journaled(self):
        """LECK 1: Live runs a started step to its end; the change gets its entry."""
        def slow(original):
            def handler(live, **arguments):
                time.sleep(0.6)                  # longer than the timeout below
                return original(live, **arguments)
            return handler
        self.patched("set_track_name", 0.25, slow)
        with self.assertRaises(LiveError) as caught:
            self.call("set_track_name", track_index=2, name="Late name")
        self.assertEqual(caught.exception.code, "timeout")
        self.assertTrue(self.wait_for(lambda: any("Late name" in t for t in self.texts())),
                        self.texts()[-3:])       # the step ends, then late() journals it
        time.sleep(0.3)                          # no second entry may follow
        self.assertEqual(SONG.tracks[2].name, "Late name")
        self.assertEqual(sum("Late name" in t for t in self.texts()), 1, self.texts()[-3:])
        self.assertIn("still working on the current step", str(caught.exception))
        self.assertIn("If the step succeeds and changes the Set, it is journaled then",
                      str(caught.exception))
        self.assertTrue(caught.exception.details.get("still_running"))
        self.undo_last(1)
        self.assertNotEqual(SONG.tracks[2].name, "Late name")

    def test_timeout_between_steps_journals_the_steps_that_ran(self):
        """LECK 1: a later step is dropped, the earlier one did change the Set."""
        hub_module = sys.modules[type(self.surface._hub).__module__]

        def chained(original):
            def handler(live, **arguments):
                original(live, **arguments)      # step 1 changes the name at once
                return hub_module.Later(lambda: {"never": True}, 2000)  # step 2 waits too long
            return handler
        self.patched("set_track_name", 0.3, chained)
        with self.assertRaises(LiveError) as caught:
            self.call("set_track_name", track_index=2, name="First step")
        self.assertEqual(caught.exception.code, "timeout")
        self.assertEqual(SONG.tracks[2].name, "First step")
        self.assertTrue(any("First step" in text for text in self.texts()), self.texts()[-3:])
        self.assertIn("Earlier steps of it did run and are journaled", str(caught.exception))
        self.assertTrue(caught.exception.details.get("journal"))
        self.assertNotIn("still_running", caught.exception.details)
        self.undo_last(1)

    def test_running_step_that_returns_later_drops_the_rest(self):
        """Review MINOR 1: the late step is journaled once, its follow-up step never runs."""
        hub_module = sys.modules[type(self.surface._hub).__module__]
        ran = []

        def slow_then_more(original):
            def handler(live, **arguments):
                time.sleep(0.6)                  # longer than the timeout below
                original(live, **arguments)
                return hub_module.Later(lambda: ran.append(1) or {}, 0)
            return handler
        self.patched("set_track_name", 0.25, slow_then_more)
        with self.assertRaises(LiveError) as caught:
            self.call("set_track_name", track_index=2, name="Late chain")
        self.assertTrue(self.wait_for(lambda: any("Late chain" in t for t in self.texts())))
        time.sleep(0.3)
        self.assertEqual(ran, [])
        self.assertEqual(sum("Late chain" in t for t in self.texts()), 1)
        self.undo_last(1)
        self.assertIn("Later steps of the command, if any, are dropped", str(caught.exception))

    def test_trouble_in_late_is_logged_counted_and_live_goes_on(self):
        """PTc:VERIFY LECK A: a step that ends after a timeout but cannot be
        journaled is logged and counted in late_failures; the gate keeps working."""
        hub = self.surface._hub
        hub_module = sys.modules[type(hub).__module__]
        context_class = hub.loaded.context_class

        def slow_then_more(original):
            def handler(live, **arguments):
                time.sleep(0.6)                  # longer than the timeout below
                original(live, **arguments)
                return hub_module.Later(lambda: {}, 0)
            return handler

        kept = context_class.__dict__["finish"]

        def failing(context, spec, *args, **kwargs):  # only this command's journal breaks
            if spec.name == "set_track_name":
                raise RuntimeError("journal gone")
            return kept(context, spec, *args, **kwargs)
        context_class.finish = failing
        self.addCleanup(setattr, context_class, "finish", kept)
        self.patched("set_track_name", 0.25, slow_then_more)
        log = self.surface.log
        start = len(log)
        failures = self.call("get_version")["late_failures"]
        with self.assertRaises(LiveError):
            self.call("set_track_name", track_index=2, name="Late trouble")
        self.assertTrue(self.wait_for(
            lambda: any("late journal for set_track_name failed" in l for l in log[start:])),
            log[start:])
        self.assertTrue(any("timed out; its later steps are dropped" in l for l in log[start:]))
        self.assertTrue(self.wait_for(
            lambda: self.call("get_version")["late_failures"] == failures + 1),
            "a journal lost after a timeout must show in bridge_status")
        self.assertEqual(self.call("get_session_info")["tempo"] > 0, True)  # drain goes on
        SONG.tracks[2].name = "Keys"

    def test_running_step_that_fails_after_the_timeout_is_not_journaled(self):
        """PTc:VERIFY: a step that fails after the timeout changes no journal and counts nothing."""
        ended = threading.Event()

        def slow_fail(original):
            def handler(live, **arguments):
                try:
                    time.sleep(0.6)              # longer than the timeout below
                    original(live, **arguments)  # it did change the Set ...
                    raise RuntimeError("step broke")  # ... and then failed
                finally:
                    ended.set()
            return handler
        self.patched("set_track_name", 0.25, slow_fail)
        count = len(self.texts())
        failures = self.call("get_version")["late_failures"]
        with self.assertRaises(LiveError) as caught:
            self.call("set_track_name", track_index=2, name="Broken late")
        self.assertTrue(caught.exception.details.get("still_running"))
        self.assertTrue(ended.wait(5))
        # the gate runs jobs in order: once this call is answered, late() is over
        self.assertEqual(self.call("get_version")["late_failures"], failures)
        self.assertEqual(len(self.texts()), count, self.texts()[-2:])
        SONG.tracks[2].name = "Keys"

    def test_timeout_between_steps_reports_a_failed_journal(self):
        """Review MINOR 1: if the entry for the earlier steps fails, the timeout says so."""
        hub = self.surface._hub
        hub_module = sys.modules[type(hub).__module__]
        context_class = hub.loaded.context_class
        kept = context_class.__dict__["finish"]

        def failing(context, spec, *args, **kwargs):
            if spec.name == "set_track_name":
                raise RuntimeError("journal gone")
            return kept(context, spec, *args, **kwargs)
        context_class.finish = failing
        self.addCleanup(setattr, context_class, "finish", kept)

        def chained(original):
            def handler(live, **arguments):
                original(live, **arguments)
                return hub_module.Later(lambda: {"never": True}, 2000)
            return handler
        self.patched("set_track_name", 0.3, chained)
        with self.assertRaises(LiveError) as caught:
            self.call("set_track_name", track_index=2, name="Unjournaled step")
        self.assertIn("their journal entry failed", str(caught.exception))
        self.assertTrue(caught.exception.details.get("journal_failed"))
        SONG.tracks[2].name = "Keys"

    def test_older_context_without_the_new_methods(self):
        """Review MINOR 4: a new hub with an older context (hot reload) falls back to
        finish() and to its own journal rule, and still counts a lost late journal."""
        hub = self.surface._hub
        context_class = hub.loaded.context_class
        for name in ("finish_late", "journals"):
            kept = context_class.__dict__[name]
            delattr(context_class, name)
            self.addCleanup(setattr, context_class, name, kept)

        def slow(original):
            def handler(live, **arguments):
                time.sleep(0.6)                  # longer than the timeout below
                return original(live, **arguments)
            return handler
        self.patched("set_track_name", 0.25, slow)
        with self.assertRaises(LiveError) as caught:
            self.call("set_track_name", track_index=2, name="Old context")
        self.assertIn("If the step succeeds and changes the Set, it is journaled then",
                      str(caught.exception))
        self.assertTrue(self.wait_for(lambda: any("Old context" in t for t in self.texts())))
        failures = self.call("get_version")["late_failures"]  # through the gate: late() is over
        self.assertEqual(sum("Old context" in t for t in self.texts()), 1)
        self.undo_last(1)

        kept_finish = context_class.__dict__["finish"]       # now the old finish() breaks

        def failing(context, spec, *args, **kwargs):
            if spec.name == "set_track_name":
                raise RuntimeError("journal gone")
            return kept_finish(context, spec, *args, **kwargs)
        context_class.finish = failing
        self.addCleanup(setattr, context_class, "finish", kept_finish)
        with self.assertRaises(LiveError):
            self.call("set_track_name", track_index=2, name="Old context lost")
        self.assertTrue(self.wait_for(
            lambda: self.call("get_version")["late_failures"] == failures + 1))
        SONG.tracks[2].name = "Keys"

    def untitled(self):
        """An untitled Set for one test; the notice flag is restored afterwards."""
        state = self.surface._hub.state
        before = (SONG.file_path, state.get("untitled_notice_given"))

        def restore():
            SONG.file_path = before[0]
            state.pop("untitled_notice_given", None)
            if before[1]:
                state["untitled_notice_given"] = before[1]
        self.addCleanup(restore)
        SONG.file_path = ""
        state.pop("untitled_notice_given", None)
        return state

    def test_late_journal_keeps_the_untitled_notice(self):
        """PTc:VERIFY LECK B (D18): nobody reads a late reply, so the notice stays for the next change."""
        def slow(original):
            def handler(live, **arguments):
                time.sleep(0.6)                  # longer than the timeout below
                return original(live, **arguments)
            return handler
        self.patched("set_track_name", 0.25, slow)
        state = self.untitled()
        with self.assertRaises(LiveError):
            self.call("set_track_name", track_index=2, name="Late untitled")
        self.assertTrue(self.wait_for(lambda: any("Late untitled" in t for t in self.texts())))
        self.assertFalse(state.get("untitled_notice_given"))
        self.assertIn("\nNote: This Set has no file yet.", tracks.set_track_volume(1, -3))
        self.undo_last(2)

    def test_timeout_between_steps_as_json_names_journal_and_notice(self):
        """PTc:VERIFY LECK B/C (D15, D18): the JSON answer of such a timeout carries the
        journal entries of the steps that ran under `journal`, and the notice."""
        hub_module = sys.modules[type(self.surface._hub).__module__]

        def chained(original):
            def handler(live, **arguments):
                original(live, **arguments)      # step 1 changes the name at once
                return hub_module.Later(lambda: {"never": True}, 2000)  # step 2 waits too long
            return handler
        self.patched("set_track_name", 0.3, chained)
        self.untitled()
        data = json.loads(tracks.set_track_name(2, "Json step", as_json=True))
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], "timeout")
        self.assertTrue(data.get("journal"), data)
        self.assertTrue(all(set(step) == {"n", "text"} for step in data["journal"]), data)
        self.assertTrue(any("Json step" in step["text"] for step in data["journal"]), data)
        self.assertTrue(data.get("notice", "").startswith("This Set has no file yet."), data)
        self.assertNotIn("notice", data.get("details", {}))   # once, in its own field
        self.assertNotIn("journal", data.get("details", {}))
        text = tracks.set_track_volume(1, -3)    # the notice was given: not again
        self.assertNotIn("Note:", text)
        self.undo_last(2)

    def test_read_command_timeout_promises_no_journal(self):
        """Delta review MINOR 1: a read that times out makes no journal promise."""
        def slow(original):
            def handler(live, **arguments):
                time.sleep(0.6)                  # longer than the timeout below
                return original(live, **arguments)
            return handler
        self.patched("get_session_info", 0.25, slow)
        with self.assertRaises(LiveError) as caught:
            self.call("get_session_info")
        time.sleep(0.6)                          # let the step end before the next test
        self.assertIn("still working on the current step", str(caught.exception))
        self.assertNotIn("journaled", str(caught.exception))

    def test_failing_late_callback_is_counted(self):
        """Delta review MINOR 2: bridge_status shows late() callbacks that raised."""
        gate = self.surface._hub.gate
        before = self.call("get_version")["late_failures"]

        def boom(_job):
            raise RuntimeError("late trouble")
        caught = []

        def client():                            # a socket thread, not Live's main thread
            try:
                gate.call(lambda: time.sleep(1.0), 0.3, late=boom)
            except Exception as problem:
                caught.append(problem)
        worker = threading.Thread(target=client)
        worker.start()
        worker.join(5)
        self.assertTrue(caught and getattr(caught[0], "code", None) == "timeout", caught)
        self.assertTrue(caught[0].details.get("still_running"),
                        "the job had not started yet: late() is never called")
        self.assertTrue(self.wait_for(
            lambda: self.call("get_version")["late_failures"] == before + 1))

    def test_meter_session_ends_after_a_timeout(self):
        """LECK 2: a measurement nobody collects stops reading; a failing one stops alone."""
        meters = sys.modules[script.__name__ + ".handlers.meters"]
        state = self.surface._hub.state
        kept = getattr(meters, "COMMAND_TIMEOUT_S", 15.0)
        meters.COMMAND_TIMEOUT_S = 0.2           # Live: 15 s
        self.addCleanup(setattr, meters, "COMMAND_TIMEOUT_S", kept)
        hub_module = sys.modules[type(self.surface._hub).__module__]

        def stuck(original):                     # like a dialog in Live: the next step waits
            def handler(live, **arguments):
                first = original(live, **arguments)
                return hub_module.Later(lambda: first, 2000)
            return handler
        self.patched("get_track_meters", 0.3, stuck)
        with self.assertRaises(LiveError):
            self.call("get_track_meters", seconds=1.0)
        self.assertTrue(state.get("meter_sessions"))      # still reading for a while
        self.assertTrue(self.wait_for(lambda: not state.get("meter_sessions"), 8.0),
                        list(state.get("meter_sessions") or {}))  # 1 s + 0.2 s + 1 s grace
        counted = []

        def broken():
            raise RuntimeError("gone")
        sessions = state.setdefault("meter_sessions", {})
        sessions["broken"] = (broken, None)
        sessions["fine"] = (lambda: counted.append(1), time.time() + 0.5)
        state["tickers"]["meter_sessions"] = ("handlers.meters", "sample_tick")
        self.assertTrue(self.wait_for(lambda: "broken" not in sessions and counted))
        self.assertTrue(counted)                 # the other session went on
        self.assertTrue(self.wait_for(lambda: "fine" not in sessions))

    def test_journal_file_failure_is_reported(self):
        """LECK 3: a failed write to the journal file shows in the listing."""
        book = self.surface._hub.state["journal"] if "journal" in self.surface._hub.state else None
        if book is None:
            self.call("set_tempo", tempo=121)
            book = self.surface._hub.state["journal"]
        blocker = tempfile.NamedTemporaryFile(delete=False)
        blocker.close()
        kept = book["file"]
        book["file"] = os.path.join(blocker.name, "sub", "journal.jsonl")  # a file as folder
        try:
            self.call("set_tempo", tempo=123)
            listing = self.call("list_changes", limit=1)
            self.assertGreaterEqual(listing.get("journal_file_lines_lost", 0), 1, listing)
            self.assertTrue(listing.get("journal_file_error"))
            self.assertIn("could not be written", safety.list_ai_changes())
        finally:
            book["file"] = kept
            book.pop("file_lost", None)
            book.pop("file_error", None)
            os.unlink(blocker.name)
        self.call("set_tempo", tempo=124)        # writes again once the path works
        with open(kept, encoding="utf-8") as handle:
            self.assertIn("124", handle.read().splitlines()[-1])

    def test_journal_lock_survives_a_hot_reload(self):
        """LECK 4: one lock for the one journal, also after a reload of its module."""
        hub = self.surface._hub
        self.call("set_tempo", tempo=125)
        lock = hub.state.get("journal_lock")
        self.assertIsNotNone(lock)
        hub.reload()
        before = self.call("list_changes", limit=1)["entries"][-1]["n"]
        threads = [threading.Thread(target=self.call, args=("set_tempo",), kwargs={"tempo": 126 + i})
                   for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertIs(hub.state.get("journal_lock"), lock)
        numbers = [e["n"] for e in self.call("list_changes", limit=0)["entries"]]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertGreaterEqual(numbers[-1], before + 4)


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

    def test_track_meters_leave_out_readings_after_a_stop(self):
        """D16: after a stop Live's meter holds the last peak for ~3 s; those readings don't count."""
        track = SONG.tracks[0]
        before = (track.output_meter_left, SONG.is_playing)

        def stop_and_hold():
            time.sleep(0.2)
            SONG.is_playing = False
            # a reading that saw the transport running is over long before this
            time.sleep(0.1)
            track.output_meter_left = 0.9  # what a reading after the stop would show

        try:
            SONG.is_playing = True
            stopper = threading.Thread(target=stop_and_hold)
            stopper.start()
            result = self.call("get_track_meters", seconds=0.6)
            stopper.join()
            self.assertEqual(result["tracks"][0]["meter_peak"], 0.5)  # 0.9 came after the stop
            self.assertTrue(result["playing"])
            self.assertGreaterEqual(result["stopped_samples"], 1)
            self.assertGreaterEqual(result["samples"], 1)
            # never playing: the stopped readings are all there is, and they say so
            idle = self.call("get_track_meters", seconds=0.2)
            self.assertFalse(idle["playing"])
            self.assertEqual(idle["samples"], idle["stopped_samples"])
            self.assertEqual(idle["tracks"][0]["meter_peak"], 0.9)
            text = self.ok(mastering.get_track_levels(0.2))
            self.assertIn("transport stopped", text)
            self.assertIn("still holds the last peak", text)
            data = json.loads(self.ok(mastering.get_track_levels(0.2, as_json=True)))
            self.assertEqual((data["playing"], data["readings"]), (False, data["readings_stopped"]))
        finally:
            track.output_meter_left, SONG.is_playing = before

    def test_track_meters_leave_out_the_held_peak_after_a_restart(self):
        """D17: a start within the hold time after a stop does not clear Live's held peak."""
        meters = sys.modules[script.__name__ + ".handlers.meters"]
        track = SONG.tracks[0]
        before = (track.output_meter_left, SONG.is_playing, getattr(meters, "HOLD_S", 3.5))
        meters.HOLD_S = 1.0  # Live: 3.5 s
        try:
            SONG.is_playing = True
            time.sleep(0.15)                 # the ticker sees the transport running
            SONG.is_playing = False
            stopped = time.time()
            time.sleep(0.15)                 # ... and the stop
            track.output_meter_left = 0.9    # the peak Live holds after the stop
            SONG.is_playing = True           # started again within the hold time
            result = self.call("get_track_meters", seconds=0.15)
            self.assertTrue(result.get("held_only"), result)
            self.assertTrue(result["playing"])
            self.assertGreaterEqual(result["held_samples"], 1)
            self.assertEqual(result["tracks"][0]["meter_peak"], 0.9)  # nothing else there
            text = self.ok(mastering.get_track_levels(0.1))
            self.assertIn("may still show the peak held from before", text)

            def fade():                      # the held peak is gone after the hold time
                time.sleep(max(0.0, stopped + 0.3 - time.time()))
                track.output_meter_left = 0.5
            fader = threading.Thread(target=fade)
            fader.start()
            result = self.call("get_track_meters", seconds=1.0)
            fader.join()
            self.assertEqual(result["tracks"][0]["meter_peak"], 0.5)  # 0.9 was held, left out
            self.assertFalse(result["held_only"])
            self.assertGreaterEqual(result["held_samples"], 1)
            data = json.loads(self.ok(mastering.get_track_levels(0.1, as_json=True)))
            self.assertEqual((data["held_only"], data["readings_held"]), (False, 0))
        finally:
            track.output_meter_left, SONG.is_playing, meters.HOLD_S = before
            self.surface._hub.state.pop("transport_state", None)  # no stop left for other tests
        # the watch runs with the bridge, so stops between measurements count too
        tickers = self.surface._hub.state.get("tickers", {})
        self.assertEqual(tickers.get("transport_watch"), ("handlers.meters", "transport_tick"))

    def test_untitled_set_notice_once(self):
        """D18: the first change in an untitled Set says that only undo_ai_change protects it."""
        state = self.surface._hub.state
        before = (SONG.file_path, state.get("untitled_notice_given"))
        try:
            SONG.file_path = ""
            state.pop("untitled_notice_given", None)
            first = self.ok(tracks.set_track_volume(1, -3))
            self.assertIn("\nNote: This Set has no file yet.", first)
            self.assertLess(first.index("Journal: #"), first.index("Note:"))
            self.assertNotIn("Note:", self.ok(tracks.set_track_volume(1, -2)))   # once
            self.assertNotIn("Note:", self.ok(session.get_session_info()))       # reads never
            SONG.file_path = r"C:\Sets\Song.als"
            self.assertNotIn("Note:", self.ok(tracks.set_track_volume(1, -1)))   # saved Set
            SONG.file_path = ""                                                 # a new untitled Set
            data = json.loads(tracks.set_track_volume(1, 0, as_json=True))
            self.assertTrue(data["notice"].startswith("This Set has no file yet."))
            self.assertNotIn("notice", data["now"])
        finally:
            SONG.file_path = before[0]
            state.pop("untitled_notice_given", None)
            if before[1]:
                state["untitled_notice_given"] = before[1]

    def test_untitled_notice_reads_the_set_on_the_main_thread(self):
        """D18: Song.file_path is read through the gate only, never on a socket thread."""
        threads = []
        song_class = type(SONG)
        kept = SONG.__dict__.pop("file_path")

        def read(song):
            threads.append(threading.current_thread() is self.pump)  # Live's main thread here
            return ""
        song_class.file_path = property(read)
        state = self.surface._hub.state
        given = state.pop("untitled_notice_given", None)
        try:
            self.assertIn("Note:", self.ok(tracks.set_track_volume(1, -3)))
            time.sleep(0.3)                  # some ticker rounds
            self.assertTrue(threads)
            self.assertTrue(all(threads), threads)
        finally:
            del song_class.file_path
            SONG.file_path = kept
            state.pop("untitled_notice_given", None)
            if given:
                state["untitled_notice_given"] = given

    def test_tickers_do_not_settle_the_journal_file(self):
        """D17: the lasting transport ticker must not fix the journal folder before a command."""
        access = sys.modules[self.surface._hub.loaded.context_class.__module__]
        journal = access.journal              # the copy the loaded context class uses
        calls, original = [], journal.prepare
        journal.prepare = lambda *a: calls.append(a)
        try:
            time.sleep(0.3)                  # ticker rounds only
            self.assertEqual(calls, [])
            self.ok(tracks.set_track_volume(1, -3))
            self.assertTrue(calls)           # commands do
        finally:
            journal.prepare = original

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

    def test_track_levels_as_json(self):
        name = SONG.tracks[0].name
        core.analyzer.accept(_osc("/ytrack", name, 0.1, 0.5, 0.05, 0.02, 0.01, 0.005, 0.0))
        try:
            data = json.loads(self.ok(mastering.get_track_levels(0.2, as_json=True)))
        finally:
            with core.analyzer._lock:
                core.analyzer._tracks.clear()
        self.assertGreaterEqual(data["readings"], 1)
        refs = [entry["ref"] for entry in data["tracks"]]
        self.assertEqual(refs[0], "track:0")
        self.assertEqual(refs[-1], "master")
        self.assertIn("return:0", refs)
        first = data["tracks"][0]
        self.assertEqual(first["peak_dbfs"], -32.0)  # 76 * 0.5 - 70
        self.assertEqual(first["meter_peak"], 0.5)
        self.assertEqual(first["y_meter"]["peak_dbfs"], -6.0)
        self.assertNotIn("air", first["y_meter"]["bands_db"])  # silent band left out
        without = json.loads(self.ok(mastering.get_track_levels(0, include_returns="false", as_json="true")))
        self.assertFalse(any(ref.startswith("return:") for ref in (e["ref"] for e in without["tracks"])))
        self.assertTrue(mastering.get_track_levels(0, as_json="maybe").startswith("Error"))

    def test_write_as_json(self):
        """Spec § 4 (D15): every write can answer JSON with ref, read-back and journal."""
        before = tracks.set_track_volume(1, -3)
        self.assertFalse(before.lstrip().startswith("{"))          # text stays the default
        data = json.loads(tracks.set_track_volume(1, -6, as_json=True))
        self.assertIs(data["ok"], True)
        self.assertEqual(data["ref"], "track:1")
        self.assertEqual(data["now"]["display"], "-6.0 dB")
        self.assertNotIn("journal", data["now"])
        self.assertTrue(data["journal"] and data["journal"][0]["n"])
        self.assertIn("fader at -6.0 dB", data["message"])
        tracks.set_track_volume(1, 0)
        data = json.loads(tracks.set_return_track_volume(0, 0.7, as_json="true"))
        self.assertEqual(data["ref"], "return:0")
        data = json.loads(devices.set_device_parameter(0, 0, "Device On", 1, use_master=True,
                                                       as_json=True))
        self.assertEqual((data["ok"], data["ref"], data["device"]), (True, "master", 0))
        data = json.loads(devices.set_device_parameter(0, 0, "Ceiling", 0, use_master=True,
                                                       as_json=True))
        self.assertEqual((data["code"], data["details"]["available"][0]), ("not_found", "Device On"))
        data = json.loads(session.set_tempo(124, as_json=True))
        self.assertIsNone(data["ref"])
        session.set_tempo(120)
        # errors: structured, with a code
        data = json.loads(tracks.set_track_volume(99, -6, as_json=True))
        self.assertEqual((data["ok"], data["code"]), (False, "out_of_range"))
        self.assertTrue(data["error"])
        data = json.loads(arrangement.clear_locators(as_json=True))
        self.assertEqual(data["code"], "needs_confirmation")
        os.environ["ABLETON_MCP_MAX_ZONE"] = "read"
        try:
            data = json.loads(tracks.set_track_name(2, "Nope", as_json=True))
            self.assertEqual(data["code"], "zone_not_allowed")
        finally:
            os.environ.pop("ABLETON_MCP_MAX_ZONE")
        self.assertTrue(tracks.set_track_mute(0, False, as_json="maybe").startswith("Error"))

    def test_write_as_json_through_mcp(self):
        """The switch reaches the tool through FastMCP's argument model."""
        import asyncio
        listed = {t.name: t for t in asyncio.run(core.mcp.list_tools())}
        writes = [n for n, info in core.TOOLS.items() if info["zone"] != core.READ]
        self.assertTrue(all("as_json" in listed[n].inputSchema["properties"] for n in writes))
        reads = [n for n, info in core.TOOLS.items()
                 if info["zone"] == core.READ and n != "get_track_levels"]  # D14 has its own
        self.assertEqual([n for n in reads if "as_json" in listed[n].inputSchema["properties"]], [])
        reply = asyncio.run(core.mcp.call_tool("set_track_mute",
                                               {"track_index": 0, "mute": False, "as_json": True}))
        blocks = reply[0] if isinstance(reply, tuple) else reply
        data = json.loads(blocks[0].text)
        self.assertEqual((data["ok"], data["ref"], data["now"]["mute"]), (True, "track:0", False))

    # tool -> (arguments, Live results, expected target); defaults are filled in
    # the way the wrapper does it, so tools called without track_index count too
    WRITE_TARGETS = {
        "als_warp_write": ({"als_path": "x.als"}, [], {"ref": None, "file": "x.als"}),
        "als_warp_derive": ({"als_path": "x.als"}, [], {"ref": None, "file": "x.als"}),
        "set_tempo_automation": ({"als_path": "x.als"}, [], {"ref": None, "file": "x.als"}),
        "set_wavetable_mod_routing": ({"als_path": "x.als"}, [], {"ref": None, "file": "x.als"}),
        "snapshot_session": ({}, [], {"ref": None}),
        "set_clip_warp_mode": ({"track_index": 1, "clip_index": 2}, [],
                               {"ref": "track:1", "clip": 2}),
        "set_warp_marker": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "set_warp_markers_batch": ({"track_index": "1", "clip_index": 2}, [],
                                   {"ref": "track:1", "clip": 2}),
        "create_locator": ({"time": 4}, [], {"ref": None}),
        "delete_locator": ({"index": 0}, [], {"ref": None}),
        "clear_locators": ({}, [], {"ref": None}),
        "create_clip": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "set_clip_name": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "fire_clip": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "stop_clip": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "add_notes_to_clip": ({"track_index": 1, "clip_index": 2}, [],
                              {"ref": "track:1", "clip": 2}),
        "replace_notes_in_clip": ({"track_index": 1, "clip_index": 2}, [],
                                  {"ref": "track:1", "clip": 2}),
        "delete_notes_from_clip": ({"track_index": 1, "clip_index": 2}, [],
                                   {"ref": "track:1", "clip": 2}),
        "humanize_clip": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "transpose_notes": ({"track_index": 1, "clip_index": 2}, [],
                            {"ref": "track:1", "clip": 2}),
        "normalize_clip": ({"track_index": 1, "clip_index": 2}, [], {"ref": "track:1", "clip": 2}),
        "generate_euclidean_rhythm": ({"track_index": 1, "clip_index": 2}, [],
                                      {"ref": "track:1", "clip": 2}),
        "load_instrument_or_effect": ({"track_index": 1}, [], {"ref": "track:1"}),
        "load_device_on_master": ({}, [], {"ref": "master"}),
        "load_device_on_return": ({"return_index": 1}, [], {"ref": "return:1"}),
        "load_drum_kit": ({"track_index": 1}, [], {"ref": "track:1"}),
        "set_device_parameter": ({"track_index": 1, "device_index": 2}, [],
                                 {"ref": "track:1", "device": 2}),
        "set_return_device_parameter": ({"return_index": 1, "device_index": 0}, [],
                                        {"ref": "return:1", "device": 0}),
        "delete_device": ({"track_index": 1, "device_index": 2, "use_return": "true",
                           "return_index": 1}, [], {"ref": "return:1", "device": 2}),
        "set_eq_mode": ({"track_index": 0, "device_index": 3, "use_master": True}, [],
                        {"ref": "master", "device": 3}),
        "set_sidechain_routing": ({"target_track_index": 2, "device_index": 0}, [],
                                  {"ref": "track:2", "device": 0}),
        "color_track_by_spectrum": ({}, [], {"ref": "track:0"}),          # default track 0
        "color_all_tracks_by_spectrum": ({}, [], {"ref": None}),
        "undo_ai_change": ({"number": 3}, [], {"ref": None}),
        "set_tempo": ({"tempo": 120}, [], {"ref": None}),
        "start_playback": ({}, [], {"ref": None}),
        "stop_playback": ({}, [], {"ref": None}),
        "undo": ({}, [], {"ref": None}),
        "redo": ({}, [], {"ref": None}),
        "set_arrangement_record": ({"enabled": True}, [], {"ref": None}),
        "fire_scene": ({"scene_index": 3}, [], {"ref": None, "scene": 3}),
        "set_scene_tempo": ({"scene_index": 3}, [], {"ref": None, "scene": 3}),
        "jump_to_time": ({"time": 8}, [], {"ref": None}),
        "set_arrangement_loop": ({"start": 0, "length": 4}, [], {"ref": None}),
        "create_midi_track": ({}, [{"index": 3}], {"ref": "track:3"}),     # Live picks it
        "create_audio_track": ({"index": 0}, [{"index": 0}], {"ref": "track:0"}),
        "set_track_name": ({"track_index": 1}, [], {"ref": "track:1"}),
        "set_track_volume": ({"track_index": 1}, [], {"ref": "track:1"}),
        "set_track_mute": ({"track_index": 1}, [], {"ref": "track:1"}),
        "set_track_color": ({"track_index": 1}, [], {"ref": "track:1"}),
        "set_track_send": ({"track_index": 1, "send_index": 0}, [], {"ref": "track:1"}),
        "group_tracks": ({"track_indices": "[1, 2]"}, [{"first_index": 1}],
                         {"ref": "track:1", "tracks": ["track:1", "track:2"]}),
        "set_return_track_volume": ({"index": 1}, [], {"ref": "return:1"}),
    }
    MORE_TARGETS = [  # flags that move the target
        ("set_device_parameter", {"track_index": 1, "device_index": 0, "use_master": "true"},
         {"ref": "master", "device": 0}),
        ("delete_device", {"track_index": 1, "device_index": 0, "use_master": True},
         {"ref": "master", "device": 0}),
        ("delete_device", {"track_index": 1, "device_index": 0}, {"ref": "track:1", "device": 0}),
        ("set_sidechain_routing", {"target_track_index": 2, "device_index": 0,
                                   "use_master_target": True}, {"ref": "master", "device": 0}),
        ("set_sidechain_routing", {"target_track_index": 2, "device_index": 0,
                                   "use_return_target": True, "return_target_index": 1},
         {"ref": "return:1", "device": 0}),
        ("set_device_parameter", {"track_index": "master", "device_index": 0},
         {"ref": "master", "device": 0}),
        ("create_midi_track", {}, {"ref": None}),        # no Live result, no guess
    ]

    def _target(self, name, given, results=()):
        import inspect
        from MCP_Server.tools import alsfile as alsfile_tools
        module = next(m for m in (arrangement, clips, devices, mastering, safety, session,
                                  tracks, alsfile_tools) if hasattr(m, name))
        bound = inspect.signature(getattr(module, name)).bind_partial(**given)
        bound.apply_defaults()
        return core.write_target(name, dict(bound.arguments), list(results))

    def test_write_targets_of_every_write_tool(self):
        writes = {n for n, info in core.TOOLS.items() if info["zone"] != core.READ}
        self.assertEqual(set(self.WRITE_TARGETS), writes)
        for name, (given, results, expected) in self.WRITE_TARGETS.items():
            with self.subTest(name):
                self.assertEqual(self._target(name, given, results), expected)
        for name, given, expected in self.MORE_TARGETS:
            with self.subTest(name, **{k: str(v) for k, v in given.items()}):
                self.assertEqual(self._target(name, given), expected)

    def test_write_as_json_outcomes(self):
        # the wrapper fills defaults: color_track_by_spectrum without track_index is track 0
        data = json.loads(mastering.color_track_by_spectrum(dry_run=True, as_json=True))
        self.assertEqual(data["ref"], "track:0")
        data = json.loads(tracks.set_track_volume(99, 0, as_json=True))  # errors name it too
        self.assertEqual((data["ok"], data["ref"]), (False, "track:99"))
        # the target of a new track comes from Live
        data = json.loads(tracks.create_midi_track(-1, as_json=True))
        self.assertEqual(data["ref"], f"track:{data['now']['index']}")
        self.ok(session.undo())
        # a write that did not happen keeps its text but is ok: false in JSON
        def no_keys(*_args, **_kwargs):
            raise tracks.winkeys.KeysUnavailable("no Live window")
        typing, tracks.winkeys.type_into_live = tracks.winkeys.type_into_live, no_keys
        try:
            text = tracks.group_tracks("[0, 1]")
            data = json.loads(tracks.group_tracks("[0, 1]", as_json=True))
        finally:
            tracks.winkeys.type_into_live = typing
        self.assertIs(type(text), str)
        self.assertTrue(text.startswith("Not grouped: no Live window. Track 0 is selected"), text)
        self.assertEqual((data["ok"], data["code"], data["ref"], data["tracks"]),
                         (False, "keys_unavailable", "track:0", ["track:0", "track:1"]))
        self.assertEqual(data["error"], text)
        # success: the read-back is the Group Track found afterwards, not the preparation
        def group(*_args, **_kwargs):
            folder = fake_live.FakeTrack("Group 1", midi=False, slots=0)
            folder.is_foldable = True
            SONG.tracks.insert(0, folder)
        typing, tracks.winkeys.type_into_live = tracks.winkeys.type_into_live, group
        count = len(SONG.tracks)
        try:
            text = tracks.group_tracks("[0, 1]")
            SONG.tracks.pop(0)
            data = json.loads(tracks.group_tracks("[0, 1]", as_json=True))
        finally:
            tracks.winkeys.type_into_live = typing
            SONG.tracks.pop(0)
        self.assertIs(type(text), str)
        self.assertTrue(text.startswith("Grouped 2 tracks"), text)
        self.assertEqual(data["message"].split("\n")[0], text.split("\n")[0])
        self.assertEqual((data["ok"], data["ref"]), (True, "track:0"))
        self.assertEqual(data["now"], {"index": 0, "name": "Group 1", "kind": "group",
                                       "track_count": count + 1})
        # an index that is no number gives no reference
        data = json.loads(tracks.set_track_volume("abc", 0, as_json=True))
        self.assertEqual((data["ok"], data["code"], data["ref"]), (False, "bad_input", None))
        # a journal note is no read-back, a look-up neither
        data = json.loads(tracks.set_track_volume(0, 0, as_json=True))
        self.assertNotIn("noted", data["now"])

    def test_lock_texts_unchanged(self):
        """Criterion: without as_json the refusals read word for word as before D15."""
        self.assertEqual(
            arrangement.clear_locators(),
            "Not executed [needs_confirmation]: clear_locators is destructive "
            f"({core.TOOLS['clear_locators']['summary']}). Ask the user; if they agree, "
            "call it again with confirm=true.")
        os.environ["ABLETON_MCP_MAX_ZONE"] = "read"
        try:
            self.assertEqual(
                tracks.set_track_name(2, "Nope"),
                "Not executed [zone_not_allowed]: set_track_name is a reversible tool and this "
                "server is limited to 'read' (ABLETON_MCP_MAX_ZONE). Ask the user before going on.")
        finally:
            os.environ.pop("ABLETON_MCP_MAX_ZONE")


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


class JournalCleanupTests(unittest.TestCase):
    """D22: per Set the newest journal files stay, the running session's included."""

    class Hub(object):
        def __init__(self):
            self.state = {}

    def setUp(self):
        import importlib
        self.journal = importlib.import_module(script.__name__ + ".journal")
        self.root = tempfile.mkdtemp(prefix="journal_cleanup_")
        kept = {name: os.environ.get(name) for name in
                ("ABLETON_MCP_JOURNAL_DIR", "ABLETON_MCP_JOURNAL_KEEP")}

        def restore():
            for name, value in kept.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.addCleanup(restore)
        os.environ["ABLETON_MCP_JOURNAL_DIR"] = self.root
        os.environ.pop("ABLETON_MCP_JOURNAL_KEEP", None)

    def files(self, set_name, count, extra=()):
        folder = os.path.join(self.root, set_name)
        os.makedirs(folder, exist_ok=True)
        names = ["2026-01-%02d_120000.jsonl" % (day + 1) for day in range(count)] + list(extra)
        for name in names:
            with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                handle.write("{}\n")
        return folder

    def start_session(self, set_name):
        hub = self.Hub()
        self.journal.prepare(hub, type("Song", (), {"name": set_name})())
        return hub

    def test_old_files_of_the_set_are_deleted(self):
        folder = self.files("Song A", 25, extra=["notes.txt", "2026-01-30_120000.jsonl.bak"])
        other = self.files("Song B", 3)
        hub = self.start_session("Song A")
        left = sorted(os.listdir(folder))
        stamped = [name for name in left if name.endswith(".jsonl")]
        self.assertEqual(stamped, ["2026-01-%02d_120000.jsonl" % day for day in range(7, 26)])
        self.assertIn("notes.txt", left)                 # not named like a journal file
        self.assertIn("2026-01-30_120000.jsonl.bak", left)
        self.assertEqual(len(os.listdir(other)), 3)      # other Sets stay
        self.assertEqual(self.journal.status(hub)["old_journal_files_deleted"], 6)
        self.journal.add(hub, "set_tempo", {"tempo": 120}, "Tempo 120")
        self.assertEqual(len([n for n in os.listdir(folder) if n.endswith(".jsonl")]), 20)

    def test_first_session_of_a_set_and_few_files(self):
        hub = self.start_session("New Song")             # no folder yet
        self.assertNotIn("journal_cleanup_error", self.journal.status(hub))
        folder = self.files("Small", 5)
        hub = self.start_session("Small")
        self.assertEqual(len(os.listdir(folder)), 5)
        self.assertNotIn("old_journal_files_deleted", self.journal.status(hub))

    def test_keep_zero_keeps_everything(self):
        os.environ["ABLETON_MCP_JOURNAL_KEEP"] = "0"
        folder = self.files("Song A", 25)
        self.start_session("Song A")
        self.assertEqual(len(os.listdir(folder)), 25)

    def test_keep_from_the_environment(self):
        os.environ["ABLETON_MCP_JOURNAL_KEEP"] = "3"
        folder = self.files("Song A", 10)
        self.start_session("Song A")
        self.assertEqual(sorted(os.listdir(folder)),
                         ["2026-01-09_120000.jsonl", "2026-01-10_120000.jsonl"])

    def test_cleanup_trouble_never_breaks_a_command(self):
        self.files("Song A", 25)
        real_remove = self.journal.os.remove

        def refuse(_path):
            raise PermissionError("locked")
        self.journal.os.remove = refuse
        self.addCleanup(setattr, self.journal.os, "remove", real_remove)
        hub = self.start_session("Song A")
        self.journal.os.remove = real_remove
        self.assertTrue(hub.state["journal"]["file"])
        self.assertIn("PermissionError", self.journal.status(hub)["journal_cleanup_error"])
        self.assertEqual(self.journal.add(hub, "set_tempo", {}, "Tempo")["n"], 1)

    def stamped(self, folder):
        return [name for name in os.listdir(folder) if name.endswith(".jsonl")]

    def test_older_settings_module_still_reads_the_environment(self):
        """Review MINOR 1: journal.py reloaded, settings.py (core) still the old one."""
        import importlib
        settings = importlib.import_module(script.__name__ + ".settings")
        rule = settings.__dict__["journal_keep"]
        del settings.journal_keep
        self.addCleanup(setattr, settings, "journal_keep", rule)
        os.environ["ABLETON_MCP_JOURNAL_KEEP"] = "0"
        folder = self.files("Song A", 25)
        self.start_session("Song A")
        self.assertEqual(len(self.stamped(folder)), 25)
        os.environ.pop("ABLETON_MCP_JOURNAL_KEEP")
        self.start_session("Song A")
        self.assertEqual(len(self.stamped(folder)), 19)

    def test_invalid_and_negative_keep(self):
        os.environ["ABLETON_MCP_JOURNAL_KEEP"] = "twenty"
        folder = self.files("Song A", 25)
        self.start_session("Song A")
        self.assertEqual(len(self.stamped(folder)), 19)       # falls back to 20
        os.environ["ABLETON_MCP_JOURNAL_KEEP"] = "-1"
        self.files("Song A", 25)
        self.start_session("Song A")
        self.assertEqual(len(self.stamped(folder)), 25)       # keeps all

    def test_journal_off_means_no_cleanup(self):
        folder = self.files("Song A", 25)
        os.environ["ABLETON_MCP_JOURNAL_DIR"] = "off"
        hub = self.start_session("Song A")
        self.assertEqual(len(self.stamped(folder)), 25)
        self.assertNotIn("journal_cleanup_error", self.journal.status(hub))

    def test_only_ascii_journal_names_are_touched(self):
        """Review MINOR 2: other digits or a trailing newline make no journal file."""
        strange = ["\u0662\u0660\u0662\u0666-\u0660\u0661-\u0660\u0661_"
                   "\u0661\u0662\u0660\u0660\u0660\u0660.jsonl"]
        os.environ["ABLETON_MCP_JOURNAL_KEEP"] = "1"      # every other journal file goes
        folder = self.files("Song A", 3, extra=strange)
        self.start_session("Song A")
        self.assertEqual(os.listdir(folder), strange)
        self.assertTrue(self.journal._JOURNAL_FILE.fullmatch("2026-01-01_120000.jsonl"))
        self.assertFalse(self.journal._JOURNAL_FILE.fullmatch("2026-01-01_120000.jsonl\n"))

    def test_unreadable_folder_is_reported(self):
        """Review MINOR 3: only a missing folder is quiet."""
        self.files("Song A", 3)
        real_listdir = self.journal.os.listdir

        def refuse(_path):
            raise PermissionError("no access")
        self.journal.os.listdir = refuse
        self.addCleanup(setattr, self.journal.os, "listdir", real_listdir)
        hub = self.start_session("Song A")
        self.journal.os.listdir = real_listdir
        self.assertIn("PermissionError", self.journal.status(hub)["journal_cleanup_error"])

    def test_untitled_and_look_alike_sets_share_a_folder(self):
        """Known limit (SAFETY): the folder goes by the Set name, untitled Sets share one."""
        folder = self.files("_untitled", 25)
        self.start_session("")
        self.assertEqual(len(self.stamped(folder)), 19)
        folder = self.files("Mix_", 25)
        self.start_session("Mix?")                       # becomes Mix_ as a folder name
        self.assertEqual(len(self.stamped(folder)), 19)


class ToolConcurrencyTests(unittest.TestCase):
    """PTc F1 / LECK E: the per-call fields in core.py need sync tools that
    FastMCP runs on its event loop thread, one after the other."""

    def test_async_tool_is_refused(self):
        async def probe_async_tool():
            return "never"
        async def probe_async_generator_tool():
            yield "never"
        for function in (probe_async_tool, probe_async_generator_tool):
            with self.assertRaises(TypeError):
                core.tool()(function)
            self.assertNotIn(function.__name__, core.TOOLS)

    def test_sync_tools_run_on_the_event_loop_thread(self):
        import asyncio
        import threading
        seen = {}

        def probe_thread_tool():
            """Test only."""
            seen["tool"] = threading.get_ident()
            return "ok"
        from mcp.types import CallToolRequest, CallToolRequestParams
        core.tool()(probe_thread_tool)
        self.addCleanup(core.TOOLS.pop, "probe_thread_tool", None)
        remove = getattr(core.mcp, "remove_tool", None)   # not in every mcp >= 1.8
        self.addCleanup(remove or core.mcp._tool_manager._tools.pop, "probe_thread_tool")
        # the handler the MCP server itself runs for tools/call, not only FastMCP
        handler = core.mcp._mcp_server.request_handlers[CallToolRequest]
        request = CallToolRequest(method="tools/call", params=CallToolRequestParams(
            name="probe_thread_tool", arguments={}))

        async def main():
            seen["loop"] = threading.get_ident()
            await handler(request)
        asyncio.run(main())
        self.assertEqual(seen.get("tool"), seen["loop"])


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
