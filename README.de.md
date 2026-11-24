# Ableton Y Bridge

[English](README.md) · **Deutsch**

Ein MCP-Server und ein Remote Script, mit denen ein KI-Assistent (Claude oder ein anderer
MCP-Client) in **Ableton Live 12** arbeiten kann: das Set lesen, Spuren und Clips anlegen,
MIDI schreiben, Geräte laden und einstellen, Warp-Marker und Locators bearbeiten und
`.als`-Projektdateien ändern, wo Lives eigene API endet.

> **Inoffiziell.** Nicht von Ableton erstellt, unterstützt oder betreut. „Ableton“ und
> „Live“ sind Marken der Ableton AG.
>
> **Zuerst Windows.** Geschrieben und getestet unter Windows 11 mit Live 12.3.6. macOS ist
> ungetestet.
>
> **Es ändert dein offenes Live-Set direkt.** Destruktive Schritte brauchen eine
> Bestätigung, und jede Änderung wird ins Journal geschrieben, gewöhnliche Änderungen
> geschehen aber sofort. Arbeite bei Sets, die dir wichtig sind, mit einer Kopie.

## Was es kann

80 Tools, nach Themen gruppiert. Jedes Tool gehört zu einer Zone: *read* (27),
*reversible* (46) oder *destructive* (7, laufen nur mit `confirm=true`). Jede Änderung
bekommt einen nummerierten Journal-Eintrag, und die meisten lassen sich einzeln
zurücknehmen; siehe [Sicherheit](#sicherheit).

| Bereich | Tools |
|---|---|
| Session und Transport | `get_session_info`, `set_tempo`, `start_playback`, `stop_playback`, `jump_to_time`, `set_arrangement_loop`, `set_arrangement_record`, `fire_scene`, `set_scene_tempo`, `switch_view`, `focus_view`, `undo`, `redo` |
| Spuren und Mixer | `get_track_info`, `create_midi_track`, `create_audio_track`, `set_track_name`, `set_track_volume` (dB wie in Live angezeigt), `set_track_mute`, `set_track_color`, `set_track_send`, `select_tracks`, `group_tracks`, `freeze_track`, `get_return_tracks`, `set_return_track_volume` |
| Clips und Noten | `create_clip`, `set_clip_name`, `fire_clip`, `stop_clip`, `add_notes_to_clip`, `replace_notes_in_clip`, `delete_notes_from_clip`, `humanize_clip`, `transpose_notes`, `normalize_clip`, `get_clip_key`, `analyze_midi_session`, `generate_euclidean_rhythm`, `generate_automation_curve` |
| Geräte und Browser | `get_browser_tree`, `get_browser_items_at_path`, `search_vst`, `load_instrument_or_effect`, `load_device_on_master`, `load_device_on_return`, `load_drum_kit`, `get_device_parameters`, `set_device_parameter`, `set_return_device_parameter`, `delete_device`, `set_eq_mode`, `set_sidechain_routing` |
| Arrangement | `get_arrangement_clips`, `set_clip_warp_mode`, `get_warp_markers`, `set_warp_marker`, `set_warp_markers_batch`, `get_locators`, `create_locator`, `delete_locator`, `clear_locators` |
| `.als`-Projektdateien | `als_warp_read`, `als_warp_write`, `als_warp_derive`, `set_tempo_automation`, `set_wavetable_mod_routing`, `snapshot_session`, `list_snapshots` |
| Pegel und Mastering-Hilfe | `get_track_levels` (alle Spuren nebeneinander, live), `get_master_analysis`, `apply_mastering_corrections`, `suggest_mastering_chain`, `color_track_by_spectrum`, `color_all_tracks_by_spectrum` |
| Sicherheit | `get_safety_status`, `list_ai_changes`, `undo_ai_change` |
| Wartung | `bridge_status` (Version und Zustandsprüfung), `hot_reload` |

Alle Spur-, Clip-, Szenen- und Geräte-Indizes zählen ab 0. Positionen und Längen sind in
Beats angegeben.

## Wie es funktioniert

```
MCP-Client  --stdio-->  MCP_Server (Python)  --TCP 127.0.0.1:9877-->  Remote Script in Live
                              ^
                              +-- UDP 7878: Pegel-/Spektrum-Frames von einem optionalen Analyzer
```

- **Remote Script** (`AbletonMCP_Remote_Script/`): läuft in Live. Ein kleiner TCP-Server
  nimmt Nachrichten der Form `{"type": ..., "params": {...}}` an. Jeder Befehl wird in
  einem **Befehlsregister** nachgeschlagen (Handler plus Metadaten: Zone, Undo-Verhalten,
  Parameter, Timeout) und auf Lives Haupt-Thread ausgeführt; die Antwort ist
  `{"status": "success", "result": ...}` oder `{"status": "error", "message": ..., "code": ...}`.
- **MCP-Server** (`MCP_Server/`): übersetzt die Tools oben in Bridge-Befehle und erledigt,
  was in Live nicht geht: Audiodateien lesen, `.als`-Dateien bearbeiten und die beiden
  Tastenkürzel tippen, für die Live keine API hat (Speichern, Gruppieren).
- **Hot Reload**: Alle Befehls-Handler lassen sich austauschen, während Live läuft
  (`hot_reload`). Der Socket-Server und die übrigen Kernmodule brauchen einen Neustart von
  Live; `bridge_status` sagt, wann das nötig ist.

## Installation (Windows)

Voraussetzungen: Ableton Live 12, Python 3.10 oder neuer.

1. Code holen und das eine nötige Paket installieren:

   ```powershell
   git clone <dieses Repository> ableton-y-bridge
   cd ableton-y-bridge
   python -m pip install "mcp[cli]>=1.8"
   ```

   Optional: Mit `python -m pip install soundfile` kann `normalize_clip` auch AIFF-, FLAC-
   und MP3-Dateien lesen (WAV mit 16 und 32 Bit geht auch ohne).

2. Das Remote Script in Lives User Library installieren:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_remote_script.ps1
   ```

   Das kopiert `AbletonMCP_Remote_Script` nach
   `Documents\Ableton\User Library\Remote Scripts\AbletonMCP`. Ein vorhandener Ordner mit
   diesem Namen wird vorher nach `Documents\Ableton\Remote Script Backups` verschoben;
   dasselbe Skript mit `-Restore` holt die letzte Sicherung zurück.

3. Live starten, **Settings > Link, Tempo & MIDI** öffnen und **AbletonMCP** als Control
   Surface wählen (Input und Output bleiben auf „None“). Lives Statuszeile zeigt
   „Ableton Y Bridge 2.2.0 on port 9877“.

4. Den Server im MCP-Client eintragen. Für Claude Desktop oder Claude Code:

   ```json
   {
     "mcpServers": {
       "AbletonMCP": {
         "command": "python",
         "args": ["C:/path/to/ableton-y-bridge/MCP_Server/server.py"]
       }
     }
   }
   ```

5. Den Assistenten bitten, `bridge_status` aufzurufen. Es meldet die Bridge-Version, die
   Zahl der Befehle und Lives Version.

Einstellungen (Host, Port, Timeouts, Taktung, Analyzer-Port, Snapshot-Ordner) sind
Umgebungsvariablen; siehe [.env.example](.env.example). Schlüssel oder Konten braucht es
nicht.

## Sicherheit

- **Zonen.** Jedes Tool ist *read*, *reversible* oder *destructive*. Destruktive Tools
  (`delete_device`, `clear_locators`, `snapshot_session` und die vier Tools, die
  `.als`-Dateien schreiben) tun nichts ohne `confirm=true`; der Assistent ist angewiesen,
  dich vorher zu fragen. Die Bridge selbst verweigert destruktive Befehle ohne diese Angabe.
- **Journal.** Jede Änderung über die Bridge bekommt eine Nummer, die in der Antwort des
  Tools steht (`Journal: #12 Track 'Bass' fader: 0.0 dB -> -6.0 dB`). `list_ai_changes`
  zeigt die Liste.
- **Antworten als JSON.** Jedes Tool, das etwas ändert, nimmt auch `as_json=true`. Es
  antwortet dann mit `ok`, dem Ziel `ref` (`track:N`, `return:N`, `master` oder `null` bei
  Änderungen am ganzen Song; `clip`, `device`, `scene`, wo angegeben), dem Stand danach in
  `now`, dem Text in `message` und den `journal`-Nummern. Fehler und Verweigerungen lauten
  `{"ok": false, "error": ..., "code": ...}`. Ohne den Schalter bleibt die Antwort Text.
- **Unbenannte Sets.** Die erste Änderung in einem Set, das noch keine Datei hat, trägt
  einen Hinweis (`Note: This Set has no file yet. ...`, in JSON das Feld `notice`): Die
  Schritte lassen sich einzeln zurücknehmen, bis Live beendet oder ein anderes Set geladen
  wird, aber nicht nach einem Absturz oder Neustart, und es gibt keinen gespeicherten Stand zum Zurückgehen. Der
  Assistent wird gebeten, vorher das Speichern vorzuschlagen.
- **Einzel-Undo.** `undo_ai_change(12)` nimmt genau Schritt 12 zurück und lässt alle
  anderen Schritte stehen. Hast du dasselbe inzwischen in Live geändert, bleibt deine
  Einstellung, und das Tool sagt es.
- **Grenze.** `ABLETON_MCP_MAX_ZONE=read` (oder `reversible`) in der Umgebung des Servers
  begrenzt, was der Assistent überhaupt tun kann.

Einzelheiten, die Liste dessen, was sich zurücknehmen lässt, und die Grenzen von alledem:
[docs/SAFETY.de.md](docs/SAFETY.de.md).

## Gut zu wissen

- **Speichern und Gruppieren laufen über die Tastatur.** Lives API kann weder ein Set
  speichern noch Spuren gruppieren. `snapshot_session` und `group_tracks` holen Lives
  Fenster nach vorn und tippen Strg+S / Strg+G. Sie tippen nicht, wenn Live nicht vorn ist
  oder einen Dialog zeigt, und sagen das. Nur Windows.
- **Journal-Dateien** landen in `%USERPROFILE%\.ableton-y-bridge\journals`; je Set
  bleiben die 20 neuesten, ältere werden endgültig gelöscht (siehe `docs/SAFETY.de.md`).
- **Speichern braucht ein Set mit Datei.** Ein unbenanntes Set, ein Set außerhalb eines
  Projektordners oder eines aus einer älteren Live-Version lässt Live einen Dialog öffnen,
  statt zu speichern.
- **Locators** lassen sich nur bei gestopptem Transport anlegen oder löschen
  (`clear_locators` stoppt ihn selbst).
- **Einfrieren** geht über Lives API nicht; `freeze_track` meldet den Zustand.
- **Eine ausgewählte Spur.** Lives API kennt keine Mehrfachauswahl.
- **Pegel, Spektrum und Lautheit während der Wiedergabe** kommen aus drei Quellen:
  - Lives eigene Meter, für alle Spuren zugleich: `get_track_levels` tastet sie einige
    Sekunden lang ab und rechnet sie in dBFS um (nach dem Fader; die Umrechnung wurde in
    Live gemessen, siehe `AbletonMCP_Remote_Script/handlers/meters.py`).
    Mit `as_json=true` antwortet es in JSON: `peak_dbfs` und `mean_dbfs` je `track:N`,
    `return:N` und `master` (`null` bei Stille) und die Zahl der Lesungen.
    Es zählen nur Lesungen bei laufendem Transport und mehr als 3,5 s nach dem letzten
    Stopp: Nach einem Stopp hält Lives Meter die letzte Spitze noch etwa 3 s, auch wenn die
    Wiedergabe neu startet. `readings_stopped` und `readings_held` sagen, wie viele Lesungen
    bei gestopptem Transport oder binnen 3,5 s nach einem Stopp fielen; gibt es keine
    anderen, werden diese genommen (`playing: false` bzw. `held_only: true`).
  - **Y Meter**, ein Max-for-Live-Gerät für beliebige Spuren: RMS, Spitzenpegel und ein
    Spektrum in fünf Bändern ([m4l/README.de.md](m4l/README.de.md)).
  - Der WASAPI-Analyzer für den ganzen Mix: Lautheit (ungefähre LUFS) und Spektrum dessen,
    was Windows abspielt (unten).

  Das alles braucht Wiedergabe; gestoppte Spuren lesen sich als still. Nichts davon ist
  eine Lautheitsmessung je Spur.
- **`.als`-Tools** bearbeiten die Datei auf der Platte und legen standardmäßig eine
  Sicherung an. Lade das Projekt in Live neu, um die Änderung zu sehen, und speichere
  zwischendurch nicht aus Live.
- **`eval_code`** (einen Python-Ausdruck in Live ausführen) gibt es als Bridge-Befehl für
  die Entwicklung; er ist abgeschaltet, solange du nicht die Datei `allow_eval.flag` neben
  dem installierten Script anlegst oder Live mit der Umgebungsvariable
  `ABLETON_MCP_ALLOW_EVAL=1` startest.
- Die Bridge lauscht nur auf der Loopback-Adresse. Alles, was eine lokale TCP-Verbindung
  öffnen kann, kann Befehle senden, wie bei anderen Remote-Script-Bridges auch.

## Optionale Teile

- `analyzer/`: ein WASAPI-Loopback-Analyzer (`audio_analyzer.py`), der misst, was Windows
  abspielt, und Pegel, Lautheit und ein Spektrum in fünf Bändern etwa fünfmal pro Sekunde
  per UDP sendet, dazu ein kleines Dashboard und ein Wrapper, um ihn als Windows-Dienst zu
  betreiben. Braucht die Pakete aus `analyzer/requirements.txt`; `list_audio_devices.py`
  zeigt, welche Ausgabe er messen kann (Auswahl mit `device_name_filter` in
  `analyzer/config.json`). Spielt Live über ein ASIO-Interface ohne Loopback-Gerät, nimm
  stattdessen Y Meter.
- `m4l/`: **Y Meter**, das Max-for-Live-Gerät für Pegel und Spektrum je Spur, und das
  Skript, das es baut ([m4l/README.de.md](m4l/README.de.md)).
- `tools/melody_check/`: Skripte, die Lives Melody-to-MIDI-Ergebnis mit der Gesangsvorlage
  vergleichen (projektspezifische Einstellungen oben in jeder Datei).
- `docs/PROMPTS.de.md`: Beispiel-Prompts.

## Für Entwickler

Ein Befehl ist eine Funktion mit Decorator; das Register ist der einzige Ort, der
Befehlsnamen kennt:

```python
# AbletonMCP_Remote_Script/handlers/tracks.py
@command("set_track_mute", zone=REVERSIBLE, summary="Mute or unmute a track",
         params=[Int("track_index"), Bool("mute")])
def set_track_mute(live, track_index, mute):
    track = live.track(track_index)
    track.mute = mute
    return {"track_index": track_index, "name": track.name, "mute": bool(track.mute)}
```

Eine neue Datei in `handlers/` legen, `hot_reload` aufrufen, und der Befehl ist da. Der
Bridge-Befehl `list_commands` liefert das ganze Register mit Zonen und Parametern.

Tests:

```powershell
python -m unittest discover -s tests          # offline, gegen ein nachgebautes Live-Objektmodell
python tests\live_protocol.py --work-dir <Arbeitsordner>   # jedes Tool einmal, gegen laufendes Live
```

Der zweite schreibt [docs/LIVE_TEST_PROTOCOL.md](docs/LIVE_TEST_PROTOCOL.md); was abgedeckt
ist und was nicht, steht in [docs/LIVE_TEST_NOTES.md](docs/LIVE_TEST_NOTES.md) (beide nur
auf Englisch). Nimm dafür ein Wegwerf-Set.

## Herkunft und Dank

Die Idee, Live von einem MCP-Server aus über einen Socket in einem Remote Script zu
steuern, und das einfache JSON-Übertragungsformat stammen von
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) und
[uisato/ableton-mcp-extended](https://github.com/uisato/ableton-mcp-extended). Dieses
Projekt begann als Fork des Letzteren. Danke euch beiden für die Anregung.

Der Code in diesem Repository ist seitdem von Grund auf neu geschrieben und enthält keinen
Code aus diesen Projekten; [docs/TEMPLATE_AUDIT.md](docs/TEMPLATE_AUDIT.md) dokumentiert den
Vergleich (auf Englisch). Das Übertragungsformat bleibt kompatibel, damit Clients, die es
sprechen, weiter funktionieren.

## Warum Open Source

Ich glaube an Open Source. Wissen und Fortschritt wachsen, wenn man sie teilt, und ich
sehe ungern, dass Fortschritt aufgehalten wird, weil jemand aus finanziellen Gründen darauf
sitzt. Gemeinsam können wir Dinge viel besser gestalten als jeder für sich.

Deshalb steht Ableton Y Bridge unter der AGPL: Jeder darf sie nutzen, untersuchen und
verbessern, und Verbesserungen bleiben für alle offen. Die kommerzielle Lizenz gibt es nur
für diejenigen, die sie in ein geschlossenes Produkt einbauen wollen.

Außerdem habe ich ein bisschen Gamer-Mentalität: Ich sehe meinen Namen gern in der
Highscore-Liste. Wenn dir die Bridge also hilft, freut mich eine Erwähnung von „Yoka“ in
deinen Credits.

## Lizenz

Copyright (C) 2026 Yoka

Ableton Y Bridge steht unter zwei Lizenzen:

- **Open Source:** [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only).
- **Kommerzielle Lizenz:** für den Einbau in ein geschlossenes oder kommerzielles Produkt
  ohne die Pflichten der AGPL. Siehe [LICENSING.de.md](LICENSING.de.md).

Beiträge brauchen die Beitragsvereinbarung aus [CONTRIBUTING.de.md](CONTRIBUTING.de.md).
Spezifikationen und Konformitätstests, die gemeinsam mit anderen Projekten entstehen,
liegen in eigenen Repositories unter der MIT-Lizenz, damit auch Projekte unter anderen
Lizenzen sie nutzen können.

Rechtlich maßgeblich ist der englische Text der Lizenzen; diese Übersetzung dient nur dem
Verständnis.
