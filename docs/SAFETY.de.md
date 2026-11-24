# Sicherheit: was der Assistent in Live darf und wie man es zurücknimmt

[English](SAFETY.md) · **Deutsch**

Die Regeln setzt der Code durch, sie stehen nicht nur in Tool-Beschreibungen.
Getestet in Live 12.3.6, siehe [LIVE_TEST_PROTOCOL.md](LIVE_TEST_PROTOCOL.md) (auf Englisch).

## 1. Zonen

Jeder Bridge-Befehl und jedes MCP-Tool gehört zu genau einer Zone.

| Zone | Bedeutung | Was durchgesetzt wird |
|---|---|---|
| read | schaut nur, ändert nichts am Set | nichts |
| reversible | ändert das Set so, dass es sich zurücknehmen lässt | Journal-Eintrag mit Nummer; Einzel-Undo, wo möglich |
| destructive | lässt sich von hier aus nicht zurücknehmen oder schreibt Dateien | läuft nur mit ausdrücklicher Bestätigung |

Stand beim Schreiben: 80 Tools (27 read, 46 reversible, 7 destructive) und 88
Bridge-Befehle (32 read, 50 reversible, 6 destructive). Das Tool `get_safety_status` und
der Bridge-Befehl `list_commands` zeigen die aktuellen Tabellen.

**Destruktive Tools:** `delete_device`, `clear_locators`, `snapshot_session` (speichert und
überschreibt damit die Datei des Sets), `als_warp_write`, `als_warp_derive`,
`set_tempo_automation`, `set_wavetable_mod_routing` (schreiben `.als`-Dateien neu).

**Destruktive Bridge-Befehle:** `delete_device`, `delete_track`, `clear_locators`,
`rebuild_locators`, `save_project`, `eval_code`.

## 2. Bestätigung

- Ein destruktives **Tool** tut nichts, solange es nicht mit `confirm=true` aufgerufen
  wird. Ohne lautet die Antwort `Not executed [needs_confirmation] ...`, und nichts hat sich
  geändert. Die Tool-Beschreibungen weisen den Assistenten an, vorher den Nutzer zu fragen
  und die Angabe nie von sich aus zu setzen.
- Ein destruktiver **Bridge-Befehl** wird abgelehnt, wenn die Anfrage nicht
  `"confirm": true` neben `type` und `params` trägt. Der MCP-Server sendet diese Angabe nur,
  während ein bestätigtes destruktives Tool läuft. Das deckt auch die alten
  Schlüsselwort-Aufrufe ab, die über `set_warp_markers_batch` destruktive Arbeit auslösen
  (`del:N`, `tempo` + `delete_track` / `clear_locators` / `rebuild_locators`).
- Harmlose Aufrufe destruktiver Tools brauchen keine Bestätigung: `als_warp_derive` mit
  `dry_run=true`, `set_tempo_automation` mit leerer Liste (liest dann nur).
- Die `.als`-Tools legen standardmäßig eine Sicherung der Datei mit Zeitstempel an.

`confirm` ist ein bewusster zweiter Schritt, kein Schloss: Ein Assistent könnte es selbst
setzen. Damit ein Mensch vor jedem destruktiven Tool klickt, trage im MCP-Client eine
Rückfrage-Regel ein. Für Claude Code in `~/.claude/settings.json` (das Präfix ist der
Servername aus deiner MCP-Konfiguration):

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

In Claude Desktop diese Tools nicht auf „immer erlauben“ stellen.

## 3. Den Server begrenzen

`ABLETON_MCP_MAX_ZONE` in der Umgebung des MCP-Servers setzen (im `env`-Block der
MCP-Client-Konfiguration):

| Wert | Wirkung |
|---|---|
| `destructive` (Standard) | alles, destruktive Tools mit Bestätigung |
| `reversible` | destruktive Tools werden auch mit `confirm=true` abgelehnt |
| `read` | der Assistent kann nur schauen |

Abgelehnte Aufrufe antworten mit `Not executed [zone_not_allowed] ...`.

## 4. Das Journal

Jeder Befehl, der das Set ändert, bekommt einen Eintrag mit laufender Nummer. Die Antworten
der Tools zeigen ihn, zum Beispiel:

```
Track 4 'Bass' fader at -6.0 dB (raw 0.7000).
Journal: #12 Track 'Bass' fader: 0.0 dB -> -6.0 dB
```

- `list_ai_changes` zeigt das Journal, `undo_ai_change(12)` nimmt **genau Schritt 12**
  zurück. Andere Schritte, frühere wie spätere, bleiben, wie sie sind. Lives eigenes Undo
  kann das nicht: Es geht nur der Reihe nach zurück.
- Im Journal stehen nur Schritte über die Bridge. Was du in Live von Hand tust, nicht.
- **Wurde dasselbe inzwischen geändert** (von dir in Live oder durch einen späteren
  Schritt), wird der Schritt nicht zurückgenommen, und der aktuelle Zustand bleibt; die
  Antwort sagt `[changed_since]`. Die Prüfung vergleicht den aktuellen Zustand mit dem, was
  der Schritt hinterlassen hat.
- Ein Schritt lässt sich einmal zurücknehmen.
- Das Journal gehört zu einem Lauf des Remote Scripts in Live. Die Nummern beginnen bei 1,
  wenn Live das Script startet, und laufen über Hot Reloads und Neustarts des MCP-Servers
  weiter. (Live startet das Script normalerweise neu, wenn ein anderes Set geladen wird;
  dieser Fall wurde nicht getestet.)
- Der Text des Journals wird außerdem nach
  `%USERPROFILE%\.ableton-y-bridge\journals\<Set-Name>\<Datum_Uhrzeit>.jsonl` geschrieben
  (eine Zeile je Schritt, eine weitere, wenn ein Schritt zurückgenommen wird). Nichts wird
  automatisch gelöscht. `ABLETON_MCP_JOURNAL_DIR` in Lives Umgebung verlegt den Ordner; der
  Wert `off` schaltet die Datei ab.

Wie sich ein Schritt zurücknehmen lässt, zeigt seine Undo-Art:

| Art | Schritte | Zurücknehmen |
|---|---|---|
| `exact` | Tempo, Spurname / Fader / Mute / Farbe / Send, Return-Fader, Clipname, Clip-Gain, Szenentempo, Loop-Klammer, EQ-Eight-Modus, Geräteparameter, Sidechain-Routing, Warp-Modus, Warp-Marker, MIDI-Noten (hinzufügen, ersetzen, löschen, humanisieren, transponieren), neue Spur, neuer Clip, geladenes Gerät (wenn nichts ersetzt wurde), neuer Audio-Clip im Arrangement, Locator angelegt / gelöscht / geleert / neu aufgebaut | `undo_ai_change(n)` stellt den vorherigen Zustand wieder her |
| `live_undo` | gelöschte Spur, gelöschtes Gerät, Laden eines Instruments, das ein anderes ersetzt hat, Warp-Reparatur über mehrere Clips, Gruppieren (Strg+G) | nur Lives eigenes Undo, solange es der jüngste Schritt ist |
| `none` | Lives Undo / Redo, Tempo Follower, Speichern, Bearbeiten von `.als`-Dateien (die haben ihre Dateisicherung) | nur zur Nachvollziehbarkeit festgehalten |

Transport- und Ansichtsaktionen (Abspielen, Stoppen, Starten, Springen, Aufnahmebereitschaft,
Ansicht wechseln) lassen das Set unverändert und kommen nicht ins Journal.

Die Wiederherstellungsdaten liegen in Lives Speicher, gebunden an die Spuren, Clips und
Parameter selbst, nicht an ihren Index. Sie bleiben richtig, wenn Spuren eingefügt oder
umsortiert werden, und enden, wenn das Set geschlossen wird. Die 400 jüngsten Schritte
lassen sich zurücknehmen; ältere behalten ihren Text.

## 5. Was das nicht abdeckt

- **Andere Clients.** Ein Programm, das einen Socket zur Bridge öffnet, unterliegt der
  Bestätigungsregel für destruktive Befehle und wird wie der MCP-Server ins Journal
  geschrieben, kann aber `"confirm": true` selbst senden. Die Bridge lauscht nur auf der
  Loopback-Adresse.
- **`ABLETON_MCP_CONFIRM=0`** in Lives Umgebung schaltet die Bestätigung auf Seiten der
  Bridge ab. Standard ist an.
- **Pegel.** Es gibt keine Obergrenze für Fader- oder Gain-Werte. Schütze Ohren und
  Lautsprecher mit einem Limiter am Ende des Abhörwegs.
- **Dateien.** Die `.als`-Tools schreiben dorthin, wohin man sie schickt; ihr Schutz sind
  die Bestätigung und die Sicherungskopie.
- **`eval_code`** bleibt abgeschaltet, solange `allow_eval.flag` nicht neben dem
  installierten Script liegt, und ist obendrein destruktiv.
- Es ist kein manipulationssicheres Prüfprotokoll: Die Journal-Datei ist eine einfache
  Textdatei.
