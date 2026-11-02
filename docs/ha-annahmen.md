# HA-Annahmen

<!-- Vorlage aus repo-vorlagen/vorlagen/ha-annahmen.md. Liegt im Repo als docs/ha-annahmen.md.
     Der HA-Beta-Bericht (repo-vorlagen/ha-beta-bericht.md) gleicht diese Liste jeden Monat mit den
     Neuerungen der HA-Beta ab. Nur festhalten, was bei einer Änderung in HA still kaputtginge. -->

Worauf sich dieses Repo bei Home Assistant verlässt. Bei jeder Änderung am Code mitpflegen.

**Getestet mit:** HA 2026.9.3 (Tests), 2026.10, 2026.11.0b1 (Tests) · **Mindestversion:** 2026.9.0 (`hacs.json`)

## Annahmen

| Annahme | Wo im Code | Abgesichert durch |
|---|---|---|
| Wiederherstellen über `async_reproduce_state` mit `context` und `reproduce_options` (`transition`); eine Domäne ist wiederherstellbar, wenn ihre Integration eine Plattform `reproduce_state` hat | `manager.py` `async_restore()`, `_async_check_supported()` | `test_recall.py::test_save_restore`, `::test_light_transition`, `test_details.py::test_unsupported_domain` |
| HAs Licht-`reproduce_state` stellt nichts her, wenn zum `color_mode` das passende Farbattribut fehlt (`color_temp_kelvin`, `hs_color`, …) | `compare.py` `COLOR_MODE_ATTRIBUTE`, `restorable_attributes()` | `test_details.py::test_light_color_mode_without_attribute` |
| Attributnamen je Domäne (Licht, Cover `current_position`/`current_tilt_position`, Klima, Medienplayer, Lüfter, …) sind die, die `reproduce_state` liest | `compare.py` `SAVED_ATTRIBUTES` | `test_compare.py::test_restorable_attributes`, `test_details.py::test_only_needed_attributes_are_saved` |
| Zwischenzustände `opening`/`closing` (Cover, Ventil) und `locking`/`unlocking`/`opening` (Schloss) | `compare.py` `TRANSITIONAL` | `test_compare.py::test_transitional_and_known`, `test_live_demo.py` (echte Demo-Jalousie) |
| Kontext einer Zustandsänderung: `user_id` = Bedienung in HA, `parent_id` = Automation/Skript (Kind des Aufrufkontexts), keins = Gerät selbst | `manager.py` `context_source()`, `_async_on_state()` | `test_recall.py::test_user_during_settling`, `::test_other_automation_after_settle`, `::test_own_later_step_relearns` |
| Ziele über `TargetSelection` + `async_extract_referenced_entity_ids` (Entität, Gerät, Bereich, Etage, Label; alte `group.*` werden zu Mitgliedern) | `manager.py` `resolve_targets()` | `test_recall.py::test_area_target`, `test_details.py::test_old_style_group_same_everywhere` |
| Neue Bedingungs-API: `Condition` mit `async_validate_config`, `ConditionConfig.target`/`.options`, `_async_check(**ConditionCheckParams)`, Plattform `async_get_conditions` + `conditions.yaml` | `condition.py` | `test_setup.py::test_condition` |
| `Store` mit Minor-Version (`_async_migrate_func`) und `UnsupportedStorageVersionError` bei neuerer Major-Version | `manager.py` `RecallStore`, `async_load()` | `test_setup.py::test_load_old_and_broken`, `::test_load_newer_major` |
| Entity-Registry-Event `entity_registry_updated`: Löschen = `action: remove` mit `entity_id`; Umbenennen = `action: update` mit `old_entity_id` (alte ID) und `entity_id` (neue ID). Recall vergisst gelöschte Entitäten und zieht Slots umbenannter auf die neue ID um | `manager.py` `_registry_filter()`, `_async_on_registry()`, `_async_rename()` | `test_details.py::test_removed_entity_is_forgotten`, `::test_renamed_entity_moves_slot` |
| `scene.create` (Dienst der Integration `scene`, Plattform `homeassistant`) nimmt `scene_id` (Slug) und `entities` als `{entity_id: {state, **attribute}}`, legt `scene.<scene_id>` an (Recall übergibt immer `recall_…`) bzw. ersetzt eine dynamische Szene mit neuem Zustandsobjekt; belegt eine Szene aus `scenes.yaml` die ID, nur Warnung im Log ohne Fehler (Recall erkennt das daran, dass das Zustandsobjekt dasselbe bleibt). Aktivieren läuft über `async_reproduce_state` und liest dieselben Attribute wie Recalls Wiederherstellen | `services.py` `create_scene()`, `manager.py` `async_scene_states()` | `test_scene.py::test_create_scene_from_slot`, `::test_scene_id_and_entities`, `::test_scene_from_yaml_is_not_replaced`, `::test_own_namespace`, `::test_without_scene_integration` |
| `_unrecorded_attributes` hält das Attribut `slots` aus dem Recorder | `sensor.py` | `test_setup.py::test_sensor_attributes` |
| `SIGNAL_CONFIG_ENTRY_CHANGED` meldet neue und entfernte Einträge anderer Integrationen (Saver-Hinweis) | `__init__.py` | `test_setup.py::test_saver_issue` |
| `async_setup_entry` darf als Custom-Integration `True` zurückgeben, `async_unload_entry` muss bis HA 2026.10 ein `bool` liefern (ab 2026.11 wäre `None` erwünscht, für eingebaute Integrationen Pflicht). Die Hilfs-Integration `fake_demo` in den Tests ist eingebaut und liefert deshalb je nach HA-Version `None` oder `True` | `__init__.py`, `tests/test_live_demo.py` | `test_live_demo.py`, `test_details.py::test_unload_flushes` |

## Fremde Integrationen

- `saver` (PiotrMachowski): nur ob ein Konfigurationseintrag existiert (`hass.config_entries.async_entries`), für
  den Reparatur-Hinweis; keine Entitäten oder Attribute.
- `demo` (nur Tests): `DemoCover` als echte Jalousie in `tests/test_live_demo.py`.

## Prüfbefehl

Gegen eine andere HA-Version: venv mit `homeassistant==<version>` und passender
`pytest-homeassistant-custom-component`, dann

```sh
.venv/bin/python -m pytest -q -p no:logging
```
