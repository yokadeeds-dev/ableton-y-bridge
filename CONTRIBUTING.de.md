# Mitwirken

[English](CONTRIBUTING.md) · **Deutsch**

Beiträge sind willkommen. Vorher ein paar Dinge.

## Lizenz deines Beitrags

Ableton Y Bridge steht unter **zwei Lizenzen** (AGPL-3.0 und eine kommerzielle Lizenz,
siehe [`LICENSING.de.md`](LICENSING.de.md)). Damit der Projektinhaber Beiträge in **beide**
aufnehmen kann, gilt für jeden Beitrag diese Vereinbarung:

> Mit dem Einreichen eines Pull Requests stimmst du zu, dass dein Beitrag unter
> **AGPL-3.0** veröffentlicht wird, **und** du räumst dem Projektinhaber (Yoka) das
> unwiderrufliche, weltweite und vergütungsfreie Recht ein, deinen Beitrag zusätzlich unter
> einer **kommerziellen Lizenz** zu lizenzieren.

Ohne diese Vereinbarung kann ein Beitrag nicht übernommen werden. Für größere Beiträge kann
eine gesondert unterschriebene Vereinbarung nötig sein.

Maßgeblich ist der englische Wortlaut der Vereinbarung in [`CONTRIBUTING.md`](CONTRIBUTING.md);
diese Übersetzung dient nur dem Verständnis.

## Ablauf

- **Zuerst ein Issue eröffnen** für Fehler und Ideen, damit wir uns einig sind, bevor du
  viel Arbeit hineinsteckst.
- Von `main` abzweigen, Commits fokussiert halten, die Änderung im Pull Request beschreiben.
- Die Offline-Tests laufen lassen: `python -m unittest discover -s tests`.
- Änderungen, die Live berühren, sollten mit einem Wegwerf-Set gegen ein laufendes Live
  geprüft werden (siehe „Für Entwickler“ in der README).
- Keine Geheimnisse und keine persönlichen Pfade in Commits; das Repository ist öffentlich.

---

*Keine Rechtsberatung. Die Vereinbarung oben ist eine Vorlage; lass sie von einem Anwalt
prüfen, bevor Geld fließt.*
