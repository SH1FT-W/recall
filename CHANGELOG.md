# Changelog

## 26.10.6 – 19.10.2026

- **Öffentlich** (SH1FT-W/recall): Lizenz Apache 2.0, `NOTICE` (Saver als Vorbild, kein Code übernommen), neue
  README im SH1FT-W-Aufbau mit Titelbild und Karten, Projektseite, HACS-Prüfung. Installation über HACS.
- Private Notizen und Screenshots aus `docs/` entfernt, Testdaten ohne Namen aus einer echten Installation.

## 26.10.5 – 19.10.2026

- Optionen ändern schreibt `.storage/recall.snapshots` nicht mehr neu (nur Vorgaben geändert, nichts Gemerktes);
  Termine und Sensor werden weiter sofort angepasst.
- Hat das verzögerte Speichern schon geschrieben, schreibt das Entladen (z. B. beim Neustart) nicht noch einmal.
- README: Versions-Badge 26.10.5.
- **Fix:** Gespeicherte Einträge ohne `saved.state` werden beim Laden verworfen wie andere kaputte Einträge
  (vorher Absturz beim Wiederherstellen).
- **Fix:** Beim Entladen wird erst das Beobachten beendet, dann geschrieben. Eine Zustandsänderung genau dazwischen
  plante sonst ein verzögertes Speichern ein, das die Datei nach dem Löschen des Eintrags wieder anlegte.
- **Speicher:** Je Domäne werden nur noch die Attribute gemerkt, die Vergleich und Wiederherstellung brauchen
  (Licht: Helligkeit, Farbmodus, Farbwerte, Effekt; Jalousie: Position, Lamellen; Klima: Zieltemperaturen, Preset,
  Lüfter, Schwenken, Luftfeuchte; Medienplayer: Lautstärke, Stumm, Quelle, Klangmodus; Lüfter, Luftbefeuchter,
  Warmwasser, Saugroboter entsprechend; alle anderen Domänen nur den Zustand). Optionslisten, Cover-URLs,
  Medienpositionen, Icons und Namen landen nicht mehr in `.storage/recall.snapshots`. Alte Einträge bleiben lesbar.
  Bewusst nicht gemerkt: `media_content_id`/`media_content_type` (Wiederherstellen würde die Wiedergabe neu
  starten).
- Medienplayer, die ständig neue Positionen melden, lösen kein Speichern und keinen Sensor-Schreibvorgang mehr aus;
  gespeichert wird nur, wenn sich ein gemerktes Feld ändert.
- Kontext-IDs werden nach einem Neustart nicht mehr übernommen (Läufe von vor dem Neustart gibt es nicht mehr).
- `docs/migration-prod.md` oben als privat gekennzeichnet.
- Werkzeuge: GitHub-Prüfung (ruff, mypy, Übersetzungen, pytest mit Abdeckungsgrenze, hassfest, wöchentlich gegen
  die neueste HA), `tools/pruefe-uebersetzungen.py`, `tools/next-version` aus der gemeinsamen Vorlage;
  pytest-Marker `english` (Vorlagenrest) entfernt.

## 26.10.4 – 16.10.2026

- **Neue Versionsnummer:** Ab jetzt zählt die Version nach **Jahr.Monat.Nummer des Releases im Monat**: `26.10.4` ist das vierte Release im Oktober 2026, im nächsten Monat geht es wieder bei `.1` los (z. B. `26.11.1`). Der Sprung von `1.2.1` auf `26.10.4` ist gewollt – Privat-Updates und Home Assistant erkennen `26.10.4` als neuer, das Update erscheint wie gewohnt.
- README: Versions-Badge zeigte noch 1.2.0.

## 1.2.1 – 16.10.2026
- Sensor „Gemerkte Zustände“: `saved_at`, `expires_at` und `changed_at` in Ortszeit, 24 h und sekundengenau
  (`2026-10-16 17:59:55+02:00` statt `2026-10-16T15:59:55.295213+00:00`). Vorlagen mit `as_datetime` gehen weiter.

## 1.2.0 – 16.10.2026
- **Übergabe zwischen Slots:** Hat ein anderer Slot (andere Automation mit eigenem Recall-Slot) nach uns genau unseren
  erwarteten Zustand gemerkt und das Gerät dann verstellt, ist das kein Handeingriff mehr. Beim Wiederherstellen geht
  unser gemerkter Zustand an diesen Slot über (ohne Bewegung, eigener Slot vergessen, Grund `handed_over`).
  Beispiel PS5 (70 → 50) + Apple TV (50 → 40): PS5 aus zuerst, dann Apple TV aus → wieder 70 statt 50.
  Fremde Automationen ohne Slot zählen weiter als Handeingriff (`changed_by: automation`).
- Editor: `recall.restore`/`recall.forget` ohne Ziel zeigen kein rotes „Kein Ziel festgelegt“ mehr (optionales Feld
  „Entitäten“ statt `target`; `target:` in YAML geht weiter).
- Diagnose schwärzt sensible Attribute (Token, Bild, Koordinaten …) und enthält die Einstellungen.
- Gemerktes wird beim Entladen sofort gespeichert; nach dem Löschen legt kein alter Termin die Datei wieder an.
- Domänen ohne Wiederherstellung (z. B. `sensor`) → `unsupported` statt fälschlich „restored“; Lichter mit Farbmodus
  ohne Farbwert kommen mit Helligkeit zurück statt gar nicht.
- Unbekannter Slot bei Restore/Forget → klare Antwort `not_saved`; gelöschte Entitäten werden vergessen.
- „Gemerkte Zustände“ und Sensor zeigen, *was* gemerkt ist (z. B. `70 % · tilt 30 %`, `on · 80 % · 2700 K`) und bis wann.
- `changed_by` nach Neustart `unknown` statt leer; Eingriff während der Fahrt nennt, wo das Gerät stehen blieb.
- Gleichzeitiges Restore desselben Slots ohne doppelte Ereignisse; paralleles `save` wird nicht weggeräumt;
  Fehlermeldungen des Geräts kommen unverpackt an; Saver-Hinweis verschwindet beim Entladen; Gruppen werden in
  Aktionen und Bedingung gleich aufgelöst.

## 1.1.0 – 16.10.2026
- Einstellungen unter **Einstellungen → Geräte & Dienste → Recall → Konfigurieren**: Standardwerte für
  „Handeingriff respektieren“, „Danach vergessen“, Toleranz, Ruhezeit, Wartezeit, Höchstdauer und „Vergessen nach“.
  Gelten, wenn eine Aktion das Feld nicht setzt; wirken sofort ohne Neustart.
- Im selben Dialog „Gemerkte Zustände“: alles Gemerkte ansehen (✋ = inzwischen von Hand verstellt) und einzelne
  Slots vergessen.
- `expires_after: 0` in `recall.save` = in diesem Aufruf nie verfallen (auch wenn in den Einstellungen eine Dauer steht).


## 1.0.0 – 16.10.2026
- Erste Fassung als Ersatz für Saver: `recall.save` / `recall.restore` / `recall.forget` mit Antwortdaten,
  benannte Slots, Ablaufzeit, Speicher über Neustarts.
- Handbetrieb-Erkennung: Recall lernt den Zustand, den die Automation anfährt, und lässt Entitäten in Ruhe, die
  danach jemand verstellt hat (Fahrt-Zwischenstände zählen nicht, Toleranz einstellbar).
- Wiederherstellen wie Szenen (Position + Lamellen, Licht mit Übergang, Klima …).
- Bedingung `recall.is_saved`, Sensor „Gemerkte Zustände“, Ereignisse, Diagnose, Hinweis solange Saver installiert ist.
- Selbst eingeschätzt Quality Scale Platin (`quality_scale.yaml`).
