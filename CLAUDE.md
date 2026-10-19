# Recall – Projektregeln

HA-Integration (`custom_components/recall`, Domain `recall`), ersetzt die HACS-Integration Saver
(PiotrMachowski, Domain `saver`; kein Code übernommen, siehe `NOTICE`). Im Alltag erprobt mit Lichtern und Jalousien,
andere Domänen nur in den Tests.

- Repo ist **öffentlich** (SH1FT-W/recall, Apache 2.0): nichts Persönliches ins Repo (keine Namen, echten Entity-IDs,
  Raum-/Slotnamen aus einer echten Installation, IPs, lokalen Pfade). Testdaten bleiben ausgedacht.
- README, Projektseite, Release-Notizen, Issue-Texte auf Englisch; CHANGELOG und Commits wie bisher.
- Lokal committen ok, Push und Releases nur nach Rückfrage. Prod nur auf ausdrücklichen Wunsch (nichts kopieren, kein
  Neustart, keine Automationen umstellen). Updates kommen über HACS (GitHub-Release mit derselben Nummer wie
  `manifest.json`, ohne „v“).

Jede Änderung = neue Version in `manifest.json` + CHANGELOG (+ Versions-Badge im README).
Versionen = Kalender-Schema `YY.M.N` (Jahr, Monat ohne Null, N = laufendes Release im Monat ab 1; ab 26.10.x, kein X.Y.Z mehr): `tools/next-version` rechnet die nächste aus (zählt nur echte, veröffentlichte GitHub-Releases des Monats, auch alte X.Y.Z, bloße Tags nicht; ohne Release im Monat → .1; jedes Release als GitHub-Release veröffentlichen). Tag/Release-Titel = genau diese Nummer ohne „v“.

## Aufbau

- `manager.py` = Herzstück (`RecallManager`, `Snapshot`): Slots `{slot: {entity_id: Snapshot}}`, Speicher
  `.storage/recall.snapshots` (`RecallStore`, Format nur über Minor-Version ändern, `Snapshot.from_dict` füllt
  fehlende Felder), ein Zustands-Listener für alle gemerkten Entitäten, ein Termin (`_async_tick`) für Beruhigen und
  Ablauf. Wiederherstellen über `async_reproduce_state` (wie Szenen) mit dem Kontext des Aufrufs.
- Handbetrieb: nach `save` **Beruhigen** (jede Änderung → 15 s Ruhefenster neu, opening/closing nie fertig, ohne
  Änderung 60 s, spätestens 10 min) → **erwarteter Zustand**. Eigene Änderungen = Kontext-ID (oder parent_id) aus
  `snap.contexts` (der merkende Automationslauf, `overwrite: false` meldet einen neuen Lauf an, Restore ohne Forget
  auch). Fremder Befehl (user_id oder parent_id) beim Beruhigen → sofort fertig mit letztem ruhigen Zustand.
  Danach Abweichung = `compare.deviation` (rein, je Domäne, Toleranz in Prozentpunkten). Entscheidung beim Restore
  live (`manual_reason`), zurück auf erwartet = wieder unverändert. Gründe: manual, moving, handed_over, unavailable,
  unsupported, not_saved.
- Übergabe (1.2): Abweichung + anderer Slot hat danach (`saved_at` ≥ unser) genau unseren erwarteten Zustand gemerkt
  (`handover_slots`) → beim Restore dessen `saved` = unser `saved`, ohne Bewegung, eigener Slot weg. Tests in
  `tests/test_handover.py` (alle Reihenfolgen, 3 Slots).
- `restore`/`forget` in `services.yaml` ohne `target` (sonst roter Editor-Hinweis), Feld `entity_id`; Schema nimmt
  weiter alle Zielfelder.
- Optionen (1.1): `settings.py` (`Settings.from_options`, alle Vorgaben aus `const.DEFAULT_*`, Abschnitte
  restore/detection/expiry), Options-Flow in `config_flow.py` = Menü „Standardeinstellungen“ + „Gemerkte Zustände“
  (Slots ansehen/vergessen; bewusst kein Button, weil gezielt je Slot). Update-Listener → `async_update_settings`
  ohne Neuladen. Aktionsfelder ohne Wert → Einstellung; `expires_after: 0` = nie.
- `compare.py` reine Logik ohne HA, neue Domänen hier + Test in `tests/test_compare.py`. `SAVED_ATTRIBUTES` legt je
  Domäne fest, welche Attribute `state_to_dict` überhaupt merkt (nur was `deviation`/`describe` und HAs
  `reproduce_state` lesen; neue Domäne = dort eintragen, sonst wird nur der Zustand gemerkt).
- Zustands-Listener speichert/schreibt den Sensor nur, wenn sich ein Feld aus `Snapshot.as_dict()` ändert
  (`last_change` allein plant nur den Termin neu). Entladen: `async_stop` vor `async_flush`, danach ist
  `_async_changed` stumm (`_stopped`).
- `services.py` (save/restore/forget mit Antwortdaten, in `async_setup`), `condition.py` + `conditions.yaml`
  (`recall.is_saved`), `sensor.py` (ein Sensor, Attribut `slots` nicht im Recorder), Reparatur-Hinweis
  `saver_installed` solange Saver eingerichtet ist (`__init__.py`, reagiert auf Eintragsänderungen).
- Logo: Variante B „Lesezeichen“ in `brand/`; Quellen + Erzeuger in `docs/logo-varianten/`
  (`erzeugen.py` schreibt SVGs + `vergleich.html`, PNGs per Edge headless).
- README-Bilder: Karten aus `docs/readme-images.json`, gerendert mit `theme/v1/readme-images/render.mjs <repo> cards`
  aus sh1ft-w.github.io. Titelbild `docs/images/readme-title.webp` (ein Bild für hell und dunkel) aus
  `tools/readme-title.html` (selbst gezeichnet, Werte ausgedacht; Rendern siehe Kommentar dort). Die Projektseite
  `docs/index.html` zeigt dasselbe Bild im Hero.

## Prüfen

- `.venv/bin/python -m pytest -q -p no:logging --cov=custom_components.recall` (≥ 95 %, Fake-Geräte
  in `tests/common.py`, Zeit über `freezer` + `async_fire_time_changed`)
- `uvx ruff check . && uvx ruff format --check .`, `uvx mypy@2.3.1 --python-executable .venv/bin/python`
- `python tools/pruefe-uebersetzungen.py` (strings.json gegen translations/*.json)
- GitHub Actions `.github/workflows/pruefung.yml` (Vorlage repo-vorlagen/vorlagen/ci-ha-integration.yml): dasselbe bei
  Push/PR auf main, montags zusätzlich gegen die neueste HA; Abdeckungsgrenze dort 98 % (`--cov-fail-under`).
- hassfest: `docker run --rm -v "$PWD/custom_components/recall:/github/workspace/custom_components/recall" ghcr.io/home-assistant/hassfest`
- Live: Beta-Container gibt es nicht mehr. Für Screenshots kurzlebigen Container aus `ghcr.io/home-assistant/home-assistant:stable`
  (Konfig in Scratchpad, `trusted_networks` + `allow_bypass_login`, Auth/Onboarding aus flode-beta-test kopiert) +
  Playwright; danach Container entfernen.
