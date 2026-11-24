# AbletonMCP Extended — Beispiel-Prompts

[English](PROMPTS.md) · **Deutsch**

Das sind die Prompts aus dem Demo-Video. Kopiere sie in Claude (Cowork oder Claude Desktop),
während AbletonMCP läuft.

---

## Prompt 1 — Grundaufbau (Claude Haiku)

> Führe das zuerst aus, um das Grundprojekt „KI-Studio“ mit den Spuren Kick, Snare, HiHat,
> Bass, Pad, Vox und einem Compressor auf der Bass-Spur anzulegen.

*(Siehe Video: 0:00–0:39)*

---

## Prompt 2 — Erweitertes Routing, Sidechain, Reverb, Pad und Delay (Claude Haiku/Sonnet)

**Voraussetzung:** Prompt 1 wurde ausgeführt. Das Projekt „KI-Studio“ besteht mit Kick,
Snare, HiHat, Bass, Pad, Vox und Compressor auf Bass.

```
Du bist ein Ableton-Assistent mit Denkvermögen für komplexe, iterative Aufgaben.
Voraussetzung: Prompt 1 (Haiku) wurde bereits ausgeführt.
Das Projekt "KI-Studio" besteht mit Kick, Snare, HiHat, Bass, Pad, Vox, Compressor auf Bass.

=== AUFGABE A — Sidechain-Routing (Kick → Bass-Compressor) ===
1. Neue MIDI-Spur anlegen: Name "[GHOST] Kick Trigger", Farbe dunkelgrau, Mute = True
2. Drum Rack mit TR-808-Kit laden (wie auf der Kick-Spur)
3. Clip in Szene 1 anlegen, 2 Takte, Note 36 auf jeder Viertel
   (Beat 1.1, 2.1, 3.1, 4.1 je Takt), Velocity 100, Dauer 0.25
4. Den Compressor auf der Bass-Spur mit der [GHOST]-Spur als Sidechain-Quelle aktivieren:
   * set_sidechain_routing mit source_track=[GHOST]-Index, target_track=Bass-Index, device_index=0
   * device.available_input_routing_types ins Log schreiben, um die verfügbaren Routing-Typen zu sehen
   * Iterieren: Abgleich über Teile des Spurnamens, Spurindex, Teilzeichenketten versuchen
   * Im Log (%APPDATA%\Ableton\Live 12.x.x\Preferences\Log.txt) nach routing_set=True suchen
   * Bei routing_set=False: Abgleichsausdruck anpassen, hot_reload aufrufen, neu versuchen
   * Erst bei routing_set=True: weiter mit Aufgabe B

=== AUFGABE B — Reverb auf Drums (Return-Spur) ===
5. Sicherstellen, dass Return-Spur A existiert (Ableton legt sie automatisch an)
6. Ein Reverb auf Return-Spur A laden: im Browser nach "Reverb" suchen und auf Return A laden
7. Reverb-Parameter auf Return A setzen:
   * Decay Time: ~2,5 s (raw ~0.55)
   * Dry/Wet: 1.0 (eine Return-Spur ist immer 100 % Wet)
8. Den Send von Drums → Return A auf ~0.25 setzen (25 % Send)
   * Bei Bedarf set_return_device_parameter nutzen; iterieren, bis der Send-Wert stimmt

=== AUFGABE C — Wavetable-Pad ===
9. Im Ableton-Browser nach einem Wavetable-Pad-Preset suchen:
   * Suchbegriffe: "Wavetable", "Pad", "Atmospheric" — get_browser_items_at_path versuchen
   * Ein atmosphärisches Pad-Preset auf die Pad-Spur laden
10. Einen Pad-Clip in Szene 1 anlegen (4 Takte):
    * Note 52 (E3), Beat 1.1, Velocity 70, Dauer 3.9
    * Note 55 (G3), Beat 1.1, Velocity 65, Dauer 3.9
    * Note 59 (B3), Beat 1.1, Velocity 60, Dauer 3.9
11. Pad-Lautstärke: 0.55

=== AUFGABE D — Eventide-Delay (VST3) laden ===
12. Im VST3-Browser nach Eventide suchen: search_vst("Eventide")
13. Wenn ein Eventide-Delay gefunden wird: auf die Pad-Spur laden (nach dem Wavetable-Instrument)
14. Wenn nicht: stattdessen Abletons "Simple Delay" laden und einstellen:
    * Zeit links/rechts auf 1/8-Note (Sync)
    * Feedback: 35 %
    * Dry/Wet: 0.30
15. Melden, was geladen wurde.

Wichtige Hinweise für alle Aufgaben:
* Audioeffekte IMMER NACH dem Instrument laden
* Nach Änderung eines Befehls-Handlers hot_reload aufrufen
* Bei Fehlern: zuerst das Log lesen, dann die Strategie anpassen — nicht blind wiederholen
```

---

## Wichtige eigene Tools im Video

| Tool | Was es tut |
|------|-------------|
| `set_sidechain_routing` | leitet eine Sidechain-Quelle über die Live-API auf einen Compressor |
| `load_device_on_return` | lädt ein Gerät direkt auf eine Return-Spur |
| `set_track_send` | setzt den Send-Pegel von einer Spur zu einem Return |
| `set_track_color` | färbt Spuren mit Abletons 70-Farben-Palette |
| `search_vst` | sucht VST3-Plugins im Browser |
| `hot_reload` | lädt die Befehls-Handler neu, ohne Live neu zu starten |

---

## Tipps zum Ausführen dieser Prompts

- **Claude Haiku** für Prompt 1 (schnell, einfaches Anlegen von Spuren)
- **Claude Sonnet** für Prompt 2 (komplexes Routing, Iteration, Abwägen)
- Ableton muss offen und das AbletonMCP Remote Script aktiv sein, bevor du startest
- Der MCP-Server muss auf Port 9877 laufen
