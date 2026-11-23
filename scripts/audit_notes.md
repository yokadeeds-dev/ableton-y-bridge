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
