# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""A small stand-in for Ableton Live's Python API, for tests without Live.

It models just enough of the Live Object Model for the Remote Script's
handlers to run: a song with tracks, clip slots, clips with notes and warp
markers, devices with parameters, a browser tree, scenes and locators.
`install()` puts fake ``Live`` and ``_Framework`` modules into sys.modules.
"""

import math
import sys
import types


class FakeParameter(object):
    def __init__(self, name, value=0.0, low=0.0, high=1.0, quantized=False, show=None):
        self.name = name
        self.value = value
        self.min = low
        self.max = high
        self.is_quantized = quantized
        self.is_enabled = True
        self._show = show

    def str_for_value(self, value):
        if self._show:
            return self._show(value)
        return "%.2f" % value


def fader_text(value):
    """Rough copy of Live's fader law: 0.85 = 0 dB, 40 dB per unit above 0.4."""
    if value <= 0.0:
        return "-inf dB"
    if value >= 0.4:
        return "%.1f dB" % ((value - 0.85) * 40.0)
    return "%.1f dB" % (-18.0 + 60.0 * math.log10(value / 0.4))


class FakeMixer(object):
    def __init__(self, sends=2):
        self.volume = FakeParameter("Volume", 0.85, show=fader_text)
        self.panning = FakeParameter("Pan", 0.0, -1.0, 1.0)
        self.sends = [FakeParameter("Send %s" % "AB"[i], 0.0) for i in range(sends)]


class FakeNote(object):
    def __init__(self, pitch, start_time, duration, velocity, mute=False):
        self.pitch, self.start_time, self.duration = pitch, start_time, duration
        self.velocity, self.mute = velocity, mute


class FakeWarpMarker(object):
    def __init__(self, sample_time=0.0, beat_time=0.0):
        self.sample_time, self.beat_time = sample_time, beat_time


class FakeClip(object):
    def __init__(self, name, length=4.0, midi=True, start_time=0.0, file_path=None):
        self.name = name
        self.length = length
        self.is_midi_clip = midi
        self.is_audio_clip = not midi
        self.is_playing = False
        self.is_recording = False
        self.muted = False
        self.start_time = start_time
        self.end_time = start_time + length
        self.start_marker, self.end_marker = 0.0, length
        self.loop_start, self.loop_end = 0.0, length
        self._notes = []
        if not midi:
            self.warping = True
            self.warp_mode = 0
            self.available_warp_modes = [0, 1, 2, 3, 4, 6]
            self.warp_markers = [FakeWarpMarker(0.0, 0.0), FakeWarpMarker(2.0, 4.0)]
            self.gain = 0.4
            self.file_path = file_path or "C:/audio/%s.wav" % name

    # notes (Live 11+ API)
    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        return [n for n in self._notes
                if from_pitch <= n.pitch < from_pitch + pitch_span
                and from_time <= n.start_time < from_time + time_span]

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        doomed = self.get_notes_extended(from_pitch, pitch_span, from_time, time_span)
        self._notes = [n for n in self._notes if n not in doomed]

    def add_new_notes(self, specs):
        for spec in specs:
            self._notes.append(FakeNote(spec.pitch, spec.start_time, spec.duration,
                                        spec.velocity, spec.mute))

    # warp markers
    def add_warp_marker(self, marker):
        self.warp_markers.append(FakeWarpMarker(marker.sample_time, marker.beat_time))

    def move_warp_marker(self, beat_time, distance):
        for marker in self.warp_markers:
            if abs(marker.beat_time - beat_time) < 1e-4:
                marker.beat_time += distance
                return
        raise RuntimeError("no marker at %s" % beat_time)

    def remove_warp_marker(self, beat_time):
        if len(self.warp_markers) <= 2:
            raise RuntimeError("cannot remove the last markers")
        self.warp_markers = [m for m in self.warp_markers if abs(m.beat_time - beat_time) >= 1e-4]

    @property
    def gain_display_string(self):
        if self.gain <= 0:
            return "-inf dB"
        return "%.1f dB" % ((self.gain - 0.4) * 40.0)


class FakeSlot(object):
    def __init__(self, clip=None):
        self.clip = clip
        self.fired = 0
        self.stopped = 0

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        self.clip = FakeClip("", length)

    def delete_clip(self):
        self.clip = None

    def fire(self):
        self.fired += 1

    def stop(self):
        self.stopped += 1


class FakeDevice(object):
    def __init__(self, name, class_name="Compressor2", parameters=None, kind="audio_effect"):
        self.name = name
        self.class_name = class_name
        self.type = kind
        self.is_active = True
        self.can_have_chains = False
        self.can_have_drum_pads = False
        self.parameters = parameters or [FakeParameter("Device On", 1.0, quantized=True),
                                         FakeParameter("Threshold", 0.5),
                                         FakeParameter("S/C On", 0.0, quantized=True)]


class FakeRouting(object):
    def __init__(self, display_name):
        self.display_name = display_name


class FakeTrack(object):
    def __init__(self, name, midi=True, slots=4):
        self.name = name
        self.has_midi_input = midi
        self.has_audio_input = not midi
        self.is_foldable = False
        self.is_grouped = False
        self.is_frozen = False
        self.can_be_frozen = True
        self.can_be_armed = True
        self.mute = self.solo = self.arm = False
        self.color_index = 0
        self.color = 0
        self.mixer_device = FakeMixer()
        self.clip_slots = [FakeSlot() for _ in range(slots)]
        self.devices = []
        self.arrangement_clips = []
        self.output_meter_left = 0.5
        self.output_meter_right = 0.25

    def delete_device(self, index):
        del self.devices[index]

    def delete_clip(self, clip):
        self.arrangement_clips.remove(clip)

    def create_audio_clip(self, path, position):
        self.arrangement_clips.append(FakeClip("audio", 8.0, midi=False,
                                               start_time=position, file_path=path))


class FakeScene(object):
    def __init__(self, name):
        self.name = name
        self.tempo = 120.0
        self.tempo_enabled = False
        self.fired = 0

    def fire(self):
        self.fired += 1


class FakeCue(object):
    def __init__(self, time, name=""):
        self.time, self.name = time, name


class FakeSongView(object):
    selected_track = None


class FakeSong(object):
    def __init__(self):
        self.name = "Test Set"
        self.file_path = "C:/Sets/Test Set.als"  # saved; the D18 test makes it untitled
        self.tempo = 120.0
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.is_playing = False
        self.current_song_time = 0.0
        self.record_mode = False
        self.loop = False
        self.loop_start = 0.0
        self.loop_length = 4.0
        self.can_undo = True
        self.can_redo = True
        self.undone = self.redone = 0
        self.view = FakeSongView()
        self.master_track = FakeTrack("Master", midi=False, slots=0)
        self.master_track.can_be_armed = False
        self.return_tracks = [FakeTrack("A-Reverb", midi=False, slots=0),
                              FakeTrack("B-Delay", midi=False, slots=0)]
        self.scenes = [FakeScene("Intro"), FakeScene("Drop")]
        self.cue_points = []
        self.tracks = []
        midi = FakeTrack("Drums")
        midi.clip_slots[0].clip = FakeClip("Beat", 4.0)
        midi.clip_slots[0].clip._notes = [FakeNote(36, 0.0, 0.25, 100), FakeNote(38, 1.0, 0.25, 90),
                                          FakeNote(60, 2.0, 0.5, 80), FakeNote(64, 3.0, 0.5, 80)]
        midi.arrangement_clips = [FakeClip("ArrMidi", 8.0)]
        midi.arrangement_clips[0]._notes = [FakeNote(60, 0.0, 1.0, 100)]
        audio = FakeTrack("Bass", midi=False)
        audio.arrangement_clips = [FakeClip("BassStem", 16.0, midi=False)]
        audio.clip_slots[0].clip = FakeClip("Loop", 4.0, midi=False)
        compressor = FakeDevice("Compressor")
        compressor.available_input_routing_types = [FakeRouting("No Input"),
                                                    FakeRouting("1-Drums"), FakeRouting("2-Bass")]
        compressor.input_routing_type = compressor.available_input_routing_types[0]
        eq = FakeDevice("EQ Eight", "Eq8")
        eq.global_mode = 0
        audio.devices = [compressor, eq]
        self.tracks = [midi, audio, FakeTrack("Keys")]
        self.master_track.devices = [FakeDevice("Limiter", "Limiter")]
        self.return_tracks[0].devices = [FakeDevice("Reverb", "Reverb")]

    def create_midi_track(self, index):
        self.tracks.insert(len(self.tracks) if index == -1 else index, FakeTrack("MIDI"))

    def create_audio_track(self, index):
        self.tracks.insert(len(self.tracks) if index == -1 else index,
                           FakeTrack("Audio", midi=False))

    def delete_track(self, index):
        del self.tracks[index]

    def start_playing(self):
        self.is_playing = True

    def stop_playing(self):
        self.is_playing = False

    def undo(self):
        self.undone += 1

    def redo(self):
        self.redone += 1

    def set_or_delete_cue(self):
        here = [c for c in self.cue_points if abs(c.time - self.current_song_time) < 1e-6]
        if here:
            self.cue_points.remove(here[0])
        else:
            self.cue_points.append(FakeCue(self.current_song_time))


class FakeBrowserItem(object):
    def __init__(self, name, uri, children=(), loadable=False, device=False):
        self.name, self.uri = name, uri
        self.children = list(children)
        self.is_loadable = loadable
        self.is_device = device
        self.is_folder = bool(children) or not loadable


class FakeBrowser(object):
    def __init__(self, song):
        self._song = song
        self.loaded = []
        leaf = lambda name, uri: FakeBrowserItem(name, uri, loadable=True, device=True)
        self.instruments = FakeBrowserItem("Instruments", "query:Synths", [
            leaf("Operator", "query:Synths#Operator"),
            FakeBrowserItem("Drum Rack", "query:Synths#Drum%20Rack", [
                leaf("Kit-Core 909", "query:Synths#Drum%20Rack:FileId_1")]),
        ])
        self.audio_effects = FakeBrowserItem("Audio Effects", "query:AudioFx", [
            leaf("Reverb", "query:AudioFx#Reverb"), leaf("Limiter", "query:AudioFx#Limiter")])
        self.midi_effects = FakeBrowserItem("MIDI Effects", "query:MidiFx", [])
        self.sounds = FakeBrowserItem("Sounds", "query:Sounds", [])
        self.drums = FakeBrowserItem("Drums", "query:Drums", [
            FakeBrowserItem("Acoustic", "query:Drums#Acoustic", [
                leaf("Kit-Session Dry", "query:Drums#Acoustic:FileId_9")])])
        self.plugins = FakeBrowserItem("Plug-Ins", "query:Plugins", [
            FakeBrowserItem("VST3", "query:Plugins#VST3", [
                FakeBrowserItem("FabFilter", "query:Plugins#VST3:FabFilter", [
                    leaf("Pro-Q 3", "query:Plugins#VST3:FabFilter:Pro-Q%203")])])])

    def load_item(self, item):
        self.loaded.append(item.uri)
        target = self._song.view.selected_track
        if target is not None:
            target.devices.append(FakeDevice(item.name))


class FakeAppView(object):
    def __init__(self):
        self.shown = []
        self.focused = []

    def available_main_views(self):
        return ["Browser", "Arranger", "Session", "Detail", "Detail/Clip", "Detail/DeviceChain"]

    def show_view(self, name):
        self.shown.append(name)

    def focus_view(self, name):
        self.focused.append(name)

    def is_view_visible(self, name):
        return name in self.shown


class FakeApplication(object):
    def __init__(self, song):
        self.view = FakeAppView()
        self.browser = FakeBrowser(song)

    def get_major_version(self):
        return 12

    def get_minor_version(self):
        return 3

    def get_bugfix_version(self):
        return 6


class FakeControlSurface(object):
    """Replacement for _Framework.ControlSurface.ControlSurface."""

    song_instance = None
    app_instance = None

    def __init__(self, c_instance):
        self.c_instance = c_instance
        self.log = []
        self.messages = []

    def song(self):
        return FakeControlSurface.song_instance

    def application(self):
        return FakeControlSurface.app_instance

    def log_message(self, *parts):
        self.log.append(" ".join(str(p) for p in parts))

    def show_message(self, text):
        self.messages.append(text)

    def update_display(self):
        pass

    def disconnect(self):
        pass


class _NoteSpec(object):
    def __init__(self, pitch, start_time, duration, velocity=100.0, mute=False, **_extra):
        self.pitch, self.start_time, self.duration = pitch, start_time, duration
        self.velocity, self.mute = velocity, mute


def install():
    """Register fake `Live` and `_Framework` modules; returns (song, app)."""
    song = FakeSong()
    app = FakeApplication(song)
    FakeControlSurface.song_instance = song
    FakeControlSurface.app_instance = app

    live = types.ModuleType("Live")
    live.Clip = types.SimpleNamespace(MidiNoteSpecification=_NoteSpec, WarpMarker=FakeWarpMarker)
    sys.modules["Live"] = live

    framework = types.ModuleType("_Framework")
    surface_module = types.ModuleType("_Framework.ControlSurface")
    surface_module.ControlSurface = FakeControlSurface
    framework.ControlSurface = surface_module
    sys.modules["_Framework"] = framework
    sys.modules["_Framework.ControlSurface"] = surface_module
    return song, app
