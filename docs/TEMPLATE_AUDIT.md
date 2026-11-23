# Overlap audit against reference code

Generated 2026-11-22 by `scripts/audit_overlap.py` from the files tracked on top of commit `979aac0`.

## What was compared

| Reference | Source | Text files |
|---|---|---|
| template | `git:bc174a1` | 17 |
| upstream | `git:origin/main` | 38 |
| ahujasid | `dir:ahujasid` | 26 |
| jpoindexter | `dir:jpoindexter` | 37 |

Own files examined: 76 (all tracked text files except this report).

## Method

- A line counts if, after trimming and collapsing whitespace, it has at least 24 characters and 3 identifier-like words and is not an import.
- **Shared line**: a counted line that occurs verbatim in any reference file.
- **Block**: 3 or more counted lines in a row that are all shared.
- **Shared shingles**: share of a file's 8-token sequences that occur in any reference (independent of line breaks and indentation).
- Lines that an API dictates (Live's entry point, SDK imports) are listed separately as interface lines.

## Result

| Measure | Value |
|---|---|
| Counted lines | 7144 |
| Shared lines | 38 (0.5 %) |
| Blocks of 3+ shared lines | 0 |
| Shared 8-token shingles | 3281 of 125116 (2.6 %) |

Against each reference on its own:

| Reference | Shared lines | Shared shingles |
|---|---:|---:|
| template | 0 (0.0 %) | 900 (0.7 %) |
| upstream | 6 (0.1 %) | 1314 (1.1 %) |
| ahujasid | 25 (0.3 %) | 1644 (1.3 %) |
| jpoindexter | 16 (0.2 %) | 2012 (1.6 %) |

## Assessment

**No block of copied code was found.** Not a single run of three consecutive
counted lines of this repository occurs in the template commit `bc174a1`, in the
current upstream, or in the two projects the template descends from.

The shared lines that remain are single lines, each of which any program doing the
same job is likely to contain:

- one-line idioms of Python and of Live's API (`self._lock = threading.Lock()`,
  `mixer = track.mixer_device`, `for cue in song.cue_points:`,
  `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)`),
- result keys that describe the thing itself (`"note_count": len(notes),`),
- names in the test double `tests/fake_live.py`, which has to mirror the method
  names of Live's API (`def create_clip(self, length):`, `def start_playing(self):`).

Against the template commit itself the count is zero once the lines dictated by an
interface are set aside (listed under "Interface lines": Live's entry point, the
control surface base class calls, standard `pyproject.toml` keys).

The shingle figure measures something weaker: sequences of eight tokens such as
`if __name__ == "__main__":` or `socket.socket(socket.AF_INET,` are shared by a large
part of all Python programs, and Max patcher files share their JSON skeleton. A few
percent is the floor for two unrelated programs in the same field; copied functions
would show up as tens of percent in single files together with blocks of shared lines.

### The references

| Name | What | Commit |
|---|---|---|
| template | uisato/ableton-mcp-extended, the commit this project was forked at | `bc174a1` (2026-03-16) |
| upstream | uisato/ableton-mcp-extended, main branch when the audit ran | `1116449` (2026-05-06) |
| ahujasid | ahujasid/ableton-mcp, default branch | `9dddc7b` (2026-09-22) |
| jpoindexter | jpoindexter/ableton-mcp, default branch | `fa4f9ec` (2026-05-01) |

### How the code was produced

- The branch starts from an empty tree (orphan branch); the template's history is not
  part of it.
- The Remote Script core (socket server, hand-over into Live's main thread, command
  register, hot reload) and all command handlers were written new, with a different
  structure: a decorator-based register instead of one dispatch function, one module
  per subject instead of one class, a job queue drained from `update_display` instead
  of scheduled messages.
- The MCP server was written new in the same way (link class, tool decorator, tools
  per subject).
- Carried over unchanged or nearly unchanged are only files that never were part of
  the template: `MCP_Server/als_warp_writer.py`, `MCP_Server/offset_calibrator.py`,
  `analyzer/`, `m4l/`, `tools/melody_check/`, `docs/PROMPTS.md` and the tests for the
  `.als` writer.

### Other sources that were checked

- The previous Remote Script contained a section labelled as ported from
  `jpoindexter/ableton-mcp` (locators, loop, humanize, transpose, return tracks,
  views). Those commands were written new as well, and that project is one of the
  references above.
- The previous Euclidean rhythm generator followed a widely circulated Bjorklund
  implementation. It was replaced by a different, shorter formulation
  (`MCP_Server/music.py`).

### Limits of this audit

It compares text. It cannot prove independent creation, and it does not look at
ideas, interfaces or names: tool names, command names and the wire format are kept on
purpose for compatibility. It is not legal advice.

## Per file

| File | Counted lines | Shared | Blocks | Shared shingles |
|---|---:|---:|---:|---:|
| `.env.example` | 13 | 0 | 0 | 0.0 % |
| `AbletonMCP_Remote_Script/__init__.py` | 6 | 0 | 0 | 0.0 % |
| `AbletonMCP_Remote_Script/browsing.py` | 80 | 0 | 0 | 3.1 % |
| `AbletonMCP_Remote_Script/errors.py` | 16 | 0 | 0 | 1.8 % |
| `AbletonMCP_Remote_Script/gate.py` | 40 | 1 | 0 | 2.1 % |
| `AbletonMCP_Remote_Script/handlers/__init__.py` | 2 | 0 | 0 | 0.0 % |
| `AbletonMCP_Remote_Script/handlers/arrangement.py` | 114 | 1 | 0 | 3.0 % |
| `AbletonMCP_Remote_Script/handlers/browser.py` | 63 | 0 | 0 | 2.6 % |
| `AbletonMCP_Remote_Script/handlers/clips.py` | 172 | 1 | 0 | 3.3 % |
| `AbletonMCP_Remote_Script/handlers/devices.py` | 208 | 0 | 0 | 1.7 % |
| `AbletonMCP_Remote_Script/handlers/legacy.py` | 61 | 0 | 0 | 0.1 % |
| `AbletonMCP_Remote_Script/handlers/locators.py` | 124 | 1 | 0 | 1.9 % |
| `AbletonMCP_Remote_Script/handlers/session.py` | 139 | 2 | 0 | 3.0 % |
| `AbletonMCP_Remote_Script/handlers/system.py` | 87 | 0 | 0 | 0.1 % |
| `AbletonMCP_Remote_Script/handlers/tempo.py` | 35 | 0 | 0 | 0.2 % |
| `AbletonMCP_Remote_Script/handlers/tracks.py` | 217 | 3 | 0 | 3.9 % |
| `AbletonMCP_Remote_Script/handlers/warp.py` | 84 | 0 | 0 | 1.8 % |
| `AbletonMCP_Remote_Script/handlers/warp_intel.py` | 154 | 0 | 0 | 0.4 % |
| `AbletonMCP_Remote_Script/hub.py` | 53 | 0 | 0 | 1.9 % |
| `AbletonMCP_Remote_Script/journal.py` | 100 | 1 | 0 | 1.3 % |
| `AbletonMCP_Remote_Script/liveaccess.py` | 124 | 1 | 0 | 1.0 % |
| `AbletonMCP_Remote_Script/noteio.py` | 93 | 0 | 0 | 4.7 % |
| `AbletonMCP_Remote_Script/registry.py` | 102 | 1 | 0 | 2.4 % |
| `AbletonMCP_Remote_Script/reloader.py` | 56 | 0 | 0 | 1.4 % |
| `AbletonMCP_Remote_Script/settings.py` | 26 | 1 | 0 | 6.6 % |
| `AbletonMCP_Remote_Script/surface.py` | 24 | 0 | 0 | 4.3 % |
| `AbletonMCP_Remote_Script/warpops.py` | 78 | 0 | 0 | 0.1 % |
| `AbletonMCP_Remote_Script/wire.py` | 77 | 0 | 0 | 4.0 % |
| `MCP_Server/__init__.py` | 2 | 0 | 0 | 0.0 % |
| `MCP_Server/als_warp_writer.py` | 406 | 2 | 0 | 0.7 % |
| `MCP_Server/analyzer_feed.py` | 37 | 2 | 0 | 8.1 % |
| `MCP_Server/app.py` | 5 | 0 | 0 | 5.0 % |
| `MCP_Server/audiofile.py` | 32 | 0 | 0 | 0.8 % |
| `MCP_Server/coerce.py` | 43 | 1 | 0 | 5.9 % |
| `MCP_Server/core.py` | 77 | 0 | 0 | 2.0 % |
| `MCP_Server/link.py` | 106 | 1 | 0 | 4.8 % |
| `MCP_Server/music.py` | 56 | 0 | 0 | 6.2 % |
| `MCP_Server/offset_calibrator.py` | 88 | 0 | 0 | 1.0 % |
| `MCP_Server/server.py` | 6 | 0 | 0 | 16.3 % |
| `MCP_Server/tools/__init__.py` | 1 | 0 | 0 | 0.0 % |
| `MCP_Server/tools/alsfile.py` | 225 | 0 | 0 | 2.0 % |
| `MCP_Server/tools/arrangement.py` | 108 | 0 | 0 | 1.6 % |
| `MCP_Server/tools/clips.py` | 258 | 2 | 0 | 3.9 % |
| `MCP_Server/tools/devices.py` | 201 | 0 | 0 | 2.0 % |
| `MCP_Server/tools/mastering.py` | 149 | 0 | 0 | 0.6 % |
| `MCP_Server/tools/safety.py` | 39 | 0 | 0 | 1.1 % |
| `MCP_Server/tools/session.py` | 95 | 0 | 0 | 1.8 % |
| `MCP_Server/tools/tracks.py` | 107 | 0 | 0 | 1.5 % |
| `MCP_Server/winkeys.py` | 112 | 0 | 0 | 0.5 % |
| `README.md` | 116 | 0 | 0 | 4.7 % |
| `analyzer/audio_analyzer.py` | 118 | 0 | 0 | 4.2 % |
| `analyzer/config.json` | 2 | 0 | 0 | 0.0 % |
| `analyzer/dashboard.py` | 121 | 1 | 0 | 2.1 % |
| `analyzer/install_and_run.bat` | 29 | 0 | 0 | 0.3 % |
| `analyzer/list_audio_devices.py` | 12 | 0 | 0 | 2.6 % |
| `analyzer/requirements.txt` | 0 | 0 | 0 | 0.0 % |
| `analyzer/service_wrapper.py` | 83 | 0 | 0 | 5.7 % |
| `docs/LIVE_TEST_NOTES.md` | 82 | 0 | 0 | 0.3 % |
| `docs/LIVE_TEST_PROTOCOL.md` | 149 | 0 | 0 | 1.3 % |
| `docs/PROMPTS.md` | 72 | 0 | 0 | 1.2 % |
| `docs/SAFETY.md` | 82 | 0 | 0 | 0.4 % |
| `m4l/AbletonMCP_Analyzer.maxpat` | 8 | 0 | 0 | 21.0 % |
| `m4l/ableton_mcp_udp.js` | 17 | 0 | 0 | 0.0 % |
| `m4l/create_m4l_device.py` | 71 | 0 | 0 | 17.0 % |
| `m4l/package_amxd.py` | 7 | 0 | 0 | 6.7 % |
| `pyproject.toml` | 12 | 0 | 0 | 23.0 % |
| `scripts/audit_notes.md` | 44 | 0 | 0 | 2.4 % |
| `scripts/audit_overlap.py` | 185 | 1 | 0 | 1.6 % |
| `tests/fake_live.py` | 199 | 10 | 0 | 4.2 % |
| `tests/live_protocol.py` | 423 | 0 | 0 | 2.1 % |
| `tests/test_als_warp_writer.py` | 161 | 0 | 0 | 1.2 % |
| `tests/test_bridge_offline.py` | 374 | 1 | 0 | 2.1 % |
| `tools/melody_check/analyze_melody_to_midi.py` | 94 | 1 | 0 | 2.1 % |
| `tools/melody_check/apply_melody_cleanup.py` | 34 | 1 | 0 | 4.8 % |
| `tools/melody_check/apply_timing_cleanup.py` | 52 | 1 | 0 | 3.3 % |
| `tools/melody_check/coverage_and_duration_fix.py` | 96 | 1 | 0 | 2.1 % |

## Every shared line

### `AbletonMCP_Remote_Script/gate.py`

- line 31 (ahujasid, jpoindexter): `self._lock = threading.Lock()`

### `AbletonMCP_Remote_Script/handlers/arrangement.py`

- line 57 (ahujasid, jpoindexter): `"note_count": len(notes),`

### `AbletonMCP_Remote_Script/handlers/clips.py`

- line 142 (ahujasid, jpoindexter): `"note_count": len(notes),`

### `AbletonMCP_Remote_Script/handlers/locators.py`

- line 41 (ahujasid): `for cue in song.cue_points:`

### `AbletonMCP_Remote_Script/handlers/session.py`

- line 82 (jpoindexter): `"volume": master.mixer_device.volume.value,`
- line 84 (jpoindexter): `"panning": master.mixer_device.panning.value,`

### `AbletonMCP_Remote_Script/handlers/tracks.py`

- line 58 (ahujasid): `"is_playing": bool(clip.is_playing),`
- line 77 (upstream, ahujasid, jpoindexter): `mixer = track.mixer_device`
- line 104 (ahujasid): `count = len(song.tracks)`

### `AbletonMCP_Remote_Script/journal.py`

- line 37 (ahujasid): `_lock = threading.Lock()`

### `AbletonMCP_Remote_Script/liveaccess.py`

- line 190 (ahujasid): `if isinstance(result, dict):`

### `AbletonMCP_Remote_Script/registry.py`

- line 159 (jpoindexter): `if not isinstance(value, list):`

### `AbletonMCP_Remote_Script/settings.py`

- line 20 (ahujasid): `HOST = os.environ.get("ABLETON_MCP_HOST", "127.0.0.1")`

### `MCP_Server/als_warp_writer.py`

- line 133 (ahujasid): `if clip_index is not None:`
- line 228 (upstream): `Raises ValueError if not found.`

### `MCP_Server/analyzer_feed.py`

- line 38 (ahujasid, jpoindexter): `self._lock = threading.Lock()`
- line 42 (ahujasid): `def start(self) -> None:`

### `MCP_Server/coerce.py`

- line 74 (jpoindexter): `if not isinstance(value, list):`

### `MCP_Server/link.py`

- line 49 (ahujasid, jpoindexter): `self._lock = threading.Lock()`

### `MCP_Server/tools/clips.py`

- line 243 (ahujasid, jpoindexter): `"note_count": len(notes),`
- line 350 (ahujasid, jpoindexter): `"note_count": len(notes),`

### `analyzer/dashboard.py`

- line 30 (ahujasid): `_lock = threading.Lock()`

### `scripts/audit_overlap.py`

- line 305 (ahujasid): `args = parser.parse_args(argv)`

### `tests/fake_live.py`

- line 127 (jpoindexter): `def create_clip(self, length):`
- line 143 (jpoindexter): `self.class_name = class_name`
- line 260 (jpoindexter): `def delete_track(self, index):`
- line 263 (jpoindexter): `def start_playing(self):`
- line 283 (ahujasid): `class FakeBrowserItem(object):`
- line 286 (ahujasid): `self.children = list(children)`
- line 287 (ahujasid): `self.is_loadable = loadable`
- line 292 (ahujasid): `class FakeBrowser(object):`
- line 339 (ahujasid): `class FakeApplication(object):`
- line 401 (ahujasid): `framework = types.ModuleType("_Framework")`

### `tests/test_bridge_offline.py`

- line 22 (ahujasid): `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`

### `tools/melody_check/analyze_melody_to_midi.py`

- line 30 (upstream): `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)`

### `tools/melody_check/apply_melody_cleanup.py`

- line 17 (upstream): `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)`

### `tools/melody_check/apply_timing_cleanup.py`

- line 27 (upstream): `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)`

### `tools/melody_check/coverage_and_duration_fix.py`

- line 36 (upstream): `s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)`

## Interface lines

- `def create_instance(c_instance):` - entry point name and signature required by Ableton Live (AbletonMCP_Remote_Script/__init__.py:9)
- `def __init__(self, c_instance):` - constructor signature: Live passes exactly this one argument (AbletonMCP_Remote_Script/surface.py:16, tests/fake_live.py:360)
- `ControlSurface.__init__(self, c_instance)` - base class constructor call required by Ableton's framework (AbletonMCP_Remote_Script/surface.py:17)
- `ControlSurface.disconnect(self)` - base class shutdown call required by Ableton's framework (AbletonMCP_Remote_Script/surface.py:58)
- `[project.optional-dependencies]` - table name defined by the pyproject.toml standard (pyproject.toml:13)
- `build-backend = "setuptools.build_meta"` - the standard way to name the setuptools build backend (pyproject.toml:26)
