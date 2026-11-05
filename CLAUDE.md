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
- Jede Änderung = neue Version in `manifest.json` + CHANGELOG (die Versions-Badge im README liest die manifest.json
  selbst). Versionen über `tools/next-version` (globale Regeln).
- `.venv` im Repo ist auch die Test-venv anderer Repos (z. B. pulse): nicht löschen oder auf andere Pakete umbauen.

## Aufbau

- `manager.py` = Herzstück (`RecallManager`, `Snapshot`), Speicher `.storage/recall.snapshots` (`RecallStore`).
- `compare.py` reine Logik ohne HA (Abweichung je Domäne), `settings.py` Optionen, `config_flow.py` mit Options-Menü
  „Standardeinstellungen“ + „Gemerkte Zustände“, `services.py` (save/restore/forget/create_scene),
  `condition.py` (`recall.is_saved`), `sensor.py` (ein Sensor), `__init__.py` mit Reparatur-Hinweis `saver_installed`.

## Warum es so ist (steht nicht im Code)

- Speicherformat nur über Minor-Version ändern; `Snapshot.from_dict` füllt fehlende Felder.
- Wiederherstellen über `async_reproduce_state` (wie Szenen) mit dem Kontext des Aufrufs.
- Handbetrieb: nach `save` erst beruhigen, dann gilt der erwartete Zustand. Eigene Änderungen erkennt Recall an der
  Kontext-ID (oder parent_id) aus `snap.contexts`; ein fremder Befehl beim Beruhigen beendet es sofort. Entscheidung
  beim Restore fällt live (`manual_reason`), zurück auf erwartet = wieder unverändert.
- Übergabe: hat ein anderer Slot danach genau unseren erwarteten Zustand gemerkt, übernimmt er unser `saved`
  (ohne Bewegung). Tests in `tests/test_handover.py` (alle Reihenfolgen, 3 Slots).
- Neue Domäne: in `compare.py` + Test in `tests/test_compare.py` **und** in `SAVED_ATTRIBUTES` eintragen, sonst wird
  nur der Zustand gemerkt.
- `restore`/`forget` in `services.yaml` ohne `target` (sonst roter Editor-Hinweis), Feld `entity_id`; Schema nimmt
  weiter alle Zielfelder.
- Gemerkte Zustände im Options-Flow, bewusst kein Button, weil gezielt je Slot. Optionen wirken ohne Neuladen.
- Zustands-Listener speichert nur bei Änderung eines Felds aus `Snapshot.as_dict()`; Attribut `slots` nicht im
  Recorder. Entladen: `async_stop` vor `async_flush`, danach ist `_async_changed` stumm (`_stopped`).
- `create_scene` legt immer `scene.recall_<id>` an, der Slot bleibt.
- Logo: Variante B „Lesezeichen“ in `brand/`; Quellen + Erzeuger in `docs/logo-varianten/`
  (`erzeugen.py` schreibt SVGs + `vergleich.html`, PNGs per Edge headless).
- README-Bilder: Titelbild aus `docs/readme-images.json` mit `theme/v1/readme-images/render.mjs <repo>`
  aus sh1ft-w.github.io: Titel als `docs/images/readme-title-{light,dark}.webp` (2560 × 1280, Fenster zeigt
  `docs/images/title-shot-*.png`, den Funktionsblock der Projektseite mit 2× aufgenommen) plus `readme-title-social.png`
  für die GitHub-Vorschau; README-Aufbau nach `repo-vorlagen/readme-muster.md`, ohne Kartentabellen. Die Projektseite zeigt das Titelbild im Hero.

## Prüfen

- `.venv/bin/python -m pytest -q -p no:logging --cov=custom_components.recall` (≥ 98 % wie in CI, Fake-Geräte
  in `tests/common.py`, Zeit über `freezer` + `async_fire_time_changed`)
- `uvx ruff@0.16.9 check . && uvx ruff@0.16.9 format --check .`, `uvx mypy@2.3.1 --python-executable .venv/bin/python`
  (Versionen wie in `pruefung.yml`)
- `python tools/pruefe-uebersetzungen.py` (strings.json gegen translations/*.json)
- GitHub Actions `.github/workflows/pruefung.yml` (Vorlage repo-vorlagen/vorlagen/ci-ha-integration.yml): dasselbe bei
  Push/PR auf main, montags zusätzlich gegen die neueste HA; Abdeckungsgrenze dort 98 % (`--cov-fail-under`).
- hassfest: `docker run --rm -v "$PWD/custom_components/recall:/github/workspace/custom_components/recall" ghcr.io/home-assistant/hassfest`
- Live: Beta-Container gibt es nicht mehr. Für Screenshots kurzlebigen Container aus `ghcr.io/home-assistant/home-assistant:stable`
  (Konfig in Scratchpad, `trusted_networks` + `allow_bypass_login`, Auth/Onboarding aus flode-beta-test kopiert) +
  Playwright; danach Container entfernen.
