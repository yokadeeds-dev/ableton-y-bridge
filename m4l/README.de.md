# Y Meter (Max for Live)

[English](README.md) · **Deutsch**

Ein kleiner Audioeffekt, der die Spur misst, auf der er sitzt, und die Werte an den
MCP-Server schickt, damit der Assistent Pegel und Spektrum je Spur sieht, während der Song
läuft.

- **Misst:** RMS und Spitzenpegel der Spur sowie den Pegel von fünf Bändern: Sub (20–60 Hz),
  Low (60–250 Hz), Mid (250 Hz–2 kHz), High (2–8 kHz), Air (8–20 kHz). Die Bänder werden mit
  `cross~`-Frequenzweichen getrennt; das RMS-Fenster ist 200 ms lang.
- **Sendet:** etwa fünfmal pro Sekunde eine OSC-Nachricht an UDP `127.0.0.1:7878`:
  `/ytrack <Spurname> rms peak sub low mid high air` (lineare Amplituden). Der Spurname
  kommt aus Live und folgt Umbenennungen.
- **Audio:** läuft unverändert durch.
- Nur aus nativen Max-Objekten gebaut; braucht keine Zusatzdateien und Live 12 Suite (oder
  Live mit Max for Live).

## Installation

`Y Meter.amxd` in diesem Ordner ist einsatzbereit. Kopiere es in deine User Library, oder
baue und kopiere es in einem Schritt:

```powershell
python m4l\build_y_meter.py --install
```

Es landet unter `User Library > Presets > Audio Effects > Max Audio Effect`.

## Benutzung

Lege **Y Meter** auf jede Spur, die du ansehen willst, meist als letztes Gerät. Bitte dann
den Assistenten um `get_track_levels`; Spuren mit dem Gerät zeigen RMS, Spitzenpegel und die
Bänder neben dem Wert von Lives eigenem Meter. Ein Y Meter auf der Main-Spur speist außerdem
`get_master_analysis`.

## Gut zu wissen

- **Wo es misst:** an seinem Platz in der Gerätekette, normalerweise also **vor** Fader und
  Pan der Spur. Lives Meterwerte in `get_track_levels` liegen **nach** dem Fader.
- **RMS, nicht Lautheit:** Es gibt keine K-Gewichtung, die Werte sind also keine LUFS.
- **Namen:** Frames werden Spuren über den Namen zugeordnet. Zwei Spuren mit gleichem Namen
  teilen sich einen Eintrag.
- **Mehrere MCP-Server:** Laufen mehrere Server (zum Beispiel haben Claude Desktop und Claude
  Code je einen gestartet), belegt der erste UDP 7878 und reicht jeden Frame an die anderen
  weiter; endet er, übernimmt ein anderer innerhalb von etwa zwei Sekunden. `bridge_status`
  zeigt die Rolle jedes Servers unter `analyzer_feed`. Server älter als Bridge 2.2.0 machen
  nicht mit: Starte sie neu. Für einen anderen Port baue eine Kopie mit `--port` und setze
  `ABLETON_MCP_ANALYZER_PORT` passend.
- Jede Instanz kostet ein wenig CPU (fünf Filter und sieben Meter).
