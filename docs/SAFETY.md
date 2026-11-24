# Safety: what the assistant may do in Live, and how to take it back

**English** · [Deutsch](SAFETY.de.md)

The rules are enforced by the code, not only stated in tool descriptions.
Tested in Live 12.3.6, see [LIVE_TEST_PROTOCOL.md](LIVE_TEST_PROTOCOL.md).

## 1. Zones

Every bridge command and every MCP tool belongs to one zone.

| Zone | Meaning | What is enforced |
|---|---|---|
| read | looks, changes nothing in the Set | nothing |
| reversible | changes the Set in a way that can be taken back | journal entry with a number; single-step undo where possible |
| destructive | cannot be taken back from here, or writes files | runs only with an explicit confirmation |

Counts at the time of writing: 80 tools (27 read, 46 reversible, 7 destructive) and
88 bridge commands (32 read, 50 reversible, 6 destructive). The tool
`get_safety_status` and the bridge command `list_commands` show the current tables.

**Destructive tools:** `delete_device`, `clear_locators`, `snapshot_session` (it saves,
which overwrites the Set's file), `als_warp_write`, `als_warp_derive`,
`set_tempo_automation`, `set_wavetable_mod_routing` (they rewrite `.als` files).

**Destructive bridge commands:** `delete_device`, `delete_track`, `clear_locators`,
`rebuild_locators`, `save_project`, `eval_code`.

## 2. Confirmation

- A destructive **tool** does nothing unless it is called with `confirm=true`. Without
  it the answer is `Not executed [needs_confirmation] ...` and nothing changed. The tool
  descriptions tell the assistant to ask the user first and never to set the flag on
  its own initiative.
- A destructive **bridge command** is refused unless the request carries
  `"confirm": true` next to `type` and `params`. The MCP server sends that flag only
  while a confirmed destructive tool is running. This also covers the old keyword calls
  that reach destructive work through `set_warp_markers_batch` (`del:N`,
  `tempo` + `delete_track` / `clear_locators` / `rebuild_locators`).
- Harmless uses of destructive tools need no confirmation: `als_warp_derive` with
  `dry_run=true`, `set_tempo_automation` with an empty list (it only reads).
- The `.als` tools keep a timestamped backup of the file by default.

`confirm` is a deliberate second step, not a lock: an assistant could set it by itself.
To have a person click before every destructive tool, add an ask rule in the MCP client.
For Claude Code, in `~/.claude/settings.json` (the prefix is the server name from your
MCP configuration):

```json
"permissions": { "ask": [
  "mcp__AbletonMCP__delete_device",
  "mcp__AbletonMCP__clear_locators",
  "mcp__AbletonMCP__snapshot_session",
  "mcp__AbletonMCP__als_warp_write",
  "mcp__AbletonMCP__als_warp_derive",
  "mcp__AbletonMCP__set_tempo_automation",
  "mcp__AbletonMCP__set_wavetable_mod_routing"
] }
```

In Claude Desktop, do not set these tools to "always allow".

## 3. Limiting the server

Set `ABLETON_MCP_MAX_ZONE` in the environment of the MCP server (the `env` block of
the MCP client configuration):

| Value | Effect |
|---|---|
| `destructive` (default) | everything, destructive tools with confirmation |
| `reversible` | destructive tools are refused even with `confirm=true` |
| `read` | the assistant can only look |

Refused calls answer `Not executed [zone_not_allowed] ...`.

## 4. The journal

Every command that changes the Set gets an entry with a running number. Tool answers
show it, for example:

```
Track 4 'Bass' fader at -6.0 dB (raw 0.7000).
Journal: #12 Track 'Bass' fader: 0.0 dB -> -6.0 dB
```

- `list_ai_changes` shows the journal, `undo_ai_change(12)` takes back **exactly step
  12**. Other steps, earlier or later, stay as they are. Live's own undo cannot do that:
  it only goes back in order.
- Only steps made through the bridge are in the journal. What you do in Live by hand
  is not.
- **If the same thing was changed since** (by you in Live, or by a later step), the
  step is not taken back and the current state stays; the answer says
  `[changed_since]`. The check compares the current state with what the step left
  behind.
- A step can be taken back once.
- **Late answers.** If Live does not answer in time (a dialog is open, Live is busy)
  but had already started a step, that step still runs to its end. If it succeeds and
  changes the Set, the change still gets its entry; the timeout error says so, and
  `list_ai_changes` shows the number. Further steps of the same command are dropped.
  A step Live had not started yet is dropped and changes nothing. If a step that ends
  after the timeout cannot be journaled, `bridge_status` counts it as `late_failures`;
  if the entry for earlier steps fails, the timeout error says so.
- If the journal file cannot be written, the journal in memory stays complete and
  `list_ai_changes` warns how many lines are missing from the file.
- The journal belongs to one run of the Remote Script inside Live. Numbers start at 1
  when Live starts the script and continue across hot reloads and across restarts of
  the MCP server. (Live normally starts the script anew when another Set is loaded;
  that case was not tested.)
- The text of the journal is also written to
  `%USERPROFILE%\.ableton-y-bridge\journals\<Set name>\<date_time>.jsonl`
  (one line per step, one more line when a step is taken back), one file per Live
  session. The 20 newest files per folder are kept, the running session's included;
  at the first command through the bridge in a Live session, older files in that
  folder are deleted for good. Only files named like the journal writes them are
  touched. `ABLETON_MCP_JOURNAL_KEEP` in Live's environment sets the number, 0 keeps
  all. `get_safety_status` reports how many files were deleted
  (`old_journal_files_deleted`) and a cleanup problem (`journal_cleanup_error`).
  `ABLETON_MCP_JOURNAL_DIR` moves the folder; the value `off` disables the file and
  the cleanup.
  Limits: the folder goes by the Set's name when the session's first command runs.
  All untitled Sets share `_untitled`, and Sets with the same name (or names that only
  differ in characters not allowed in file names) share a folder and its 20 places.
  A Set saved under a new name during a session keeps writing to the old folder until
  the session ends. "Newest" goes by the start time in the file name; a clock set back
  can upset the order.

How a step can be taken back is shown as its undo kind:

| Kind | Steps | Taking it back |
|---|---|---|
| `exact` | tempo, track name / fader / mute / color / send, return fader, clip name, clip gain, scene tempo, loop brace, EQ Eight mode, device parameters, sidechain routing, warp mode, warp markers, MIDI notes (add, replace, delete, humanize, transpose), new track, new clip, loaded device (if nothing was replaced), new arrangement audio clip, locator created / deleted / cleared / rebuilt | `undo_ai_change(n)` restores the previous state |
| `live_undo` | deleted track, deleted device, loading an instrument that replaced another one, warp repair on several clips, grouping (Ctrl+G) | only Live's own undo, while it is the most recent step |
| `none` | Live undo / redo, tempo follower, saving, `.als` file edits (those have their file backup) | recorded for the record only |

Transport and view actions (play, stop, launch, jump, record arm, switching views) leave
the Set as it is and are not journaled.

The restore information lives in Live's memory, attached to the tracks, clips and
parameters themselves, not to their index. It stays correct when tracks are inserted
or reordered and ends when the Set is closed. The 400 most recent steps can be taken
back; older ones keep their text.

## 5. What this does not cover

- **Other clients.** A program that opens a socket to the bridge is bound by the
  confirmation rule for destructive commands and is journaled like the MCP server,
  but it can send `"confirm": true` itself. The bridge listens on the loopback
  address only.
- **`ABLETON_MCP_CONFIRM=0`** in Live's environment switches the bridge-side
  confirmation off. The default is on.
- **Levels.** There is no cap on fader or gain values. Protect your ears and speakers
  with a limiter at the end of the monitor path.
- **Files.** The `.als` tools write where they are told to; their protection is the
  confirmation and the backup copy.
- **`eval_code`** stays switched off unless `allow_eval.flag` exists next to the
  installed script or Live runs with the environment variable
  `ABLETON_MCP_ALLOW_EVAL=1`, and it is destructive on top of that.
- It is not a tamper-proof audit log: the journal file is a plain text file.
- **Untitled Sets.** Changes are allowed in a Set that has no file yet, but the
  journal's undo lives only in memory and there is no saved state to fall back on.
  The first change there carries a notice (`Note: ...` in text, `notice` in JSON)
  that says so; it comes again after a change in a saved Set.
