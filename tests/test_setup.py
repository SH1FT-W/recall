"""Einrichtung, Speicher über Neustart, Hinweis auf Saver, Bedingung, Diagnose, Entfernen."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import condition, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from common import COVER, LIGHT, FakeHome, automation, call, wait
from custom_components.recall.const import DOMAIN, STORAGE_KEY
from custom_components.recall.diagnostics import async_get_config_entry_diagnostics


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Recall"
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_survives_restart(
    hass: HomeAssistant, home: FakeHome, setup, freezer, hass_storage: dict[str, Any]
) -> None:
    await automation(hass, 40, slot="apple_tv")
    await wait(hass, freezer, 16)
    await call(hass, "save", entity_id=LIGHT, slot="licht")  # noch beim Beruhigen
    await wait(hass, freezer, 5)
    stored = hass_storage[STORAGE_KEY]
    assert stored["version"] == 1 and stored["minor_version"] == 2
    assert stored["data"]["slots"]["apple_tv"][COVER]["settled"] is True

    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    manager = setup.runtime_data
    assert manager.get("apple_tv", COVER).settled
    light = manager.get("licht", LIGHT)
    assert not light.settled  # beginnt nach dem Neustart neu zu beruhigen
    assert hass.states.get("sensor.recall_saved_states").state == "2"

    home.cover(70)
    await hass.async_block_till_done()
    result = await call(hass, "restore", slot="apple_tv")
    assert result["skipped"][0]["reason"] == "manual"


async def test_load_old_and_broken(hass: HomeAssistant, home: FakeHome, hass_storage: dict[str, Any]) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 0,
        "key": STORAGE_KEY,
        "data": {
            "slots": {
                "a": {
                    COVER: {
                        "saved": {"state": "open", "attributes": {"current_position": 100}},
                        "contexts": ["lauf-vor-dem-neustart"],
                    },
                    LIGHT: {"kaputt": True},
                },
                "leer": {LIGHT: {}},
                "ohne_state": {LIGHT: {"saved": {"attributes": {"brightness": 10}}}},
                "kein_dict": {LIGHT: {"saved": "on"}},
            }
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    manager = entry.runtime_data
    assert list(manager.slots) == ["a"]
    assert list(manager.slots["a"]) == [COVER]
    assert manager.get("a", COVER).tolerance == 3
    assert manager.get("a", COVER).contexts == []  # Läufe von vor dem Neustart gibt es nicht mehr


async def test_load_newer_major(hass: HomeAssistant, home: FakeHome, hass_storage: dict[str, Any]) -> None:
    hass_storage[STORAGE_KEY] = {"version": 2, "minor_version": 1, "key": STORAGE_KEY, "data": {"slots": {"a": {}}}}
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.slots == {}


async def test_expired_while_down(hass: HomeAssistant, home: FakeHome, hass_storage: dict[str, Any]) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "slots": {
                "a": {
                    COVER: {
                        "saved": {"state": "open", "attributes": {"current_position": 100}},
                        "saved_at": "2020-01-01T00:00:00+00:00",
                        "expires_at": "2020-01-01T01:00:00+00:00",
                    }
                }
            }
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.slots == {}


async def test_saver_issue(hass: HomeAssistant, home: FakeHome) -> None:
    saver = MockConfigEntry(domain="saver", data={})
    saver.add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "saver_installed")
    await hass.config_entries.async_remove(saver.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, "saver_installed") is None


async def test_remove_entry(hass: HomeAssistant, home: FakeHome, setup, hass_storage: dict[str, Any], freezer) -> None:
    await call(hass, "save", entity_id=COVER)
    await wait(hass, freezer, 5)
    assert STORAGE_KEY in hass_storage
    home.cover(50)  # Änderung steht noch zum verzögerten Speichern an
    await hass.async_block_till_done()
    await hass.config_entries.async_remove(setup.entry_id)
    await hass.async_block_till_done()
    assert STORAGE_KEY not in hass_storage
    await wait(hass, freezer, 5)
    assert STORAGE_KEY not in hass_storage  # kein alter Termin legt die Datei wieder an


async def test_unload_stops_before_flush(
    hass: HomeAssistant, home: FakeHome, setup, hass_storage: dict[str, Any], freezer
) -> None:
    """Eine Zustandsänderung zwischen Schreiben und Stoppen darf nach dem Entladen nichts mehr speichern."""
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    manager = setup.runtime_data
    original_flush = manager.async_flush

    async def flush_with_change() -> None:
        home.cover(70)  # kommt genau im Fenster zwischen Flush und Stop an
        await hass.async_block_till_done()
        await original_flush()

    with patch.object(manager, "async_flush", flush_with_change):
        assert await hass.config_entries.async_unload(setup.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage[STORAGE_KEY]["data"]["slots"]["default"][COVER]
    assert stored["changed_at"] is None
    await wait(hass, freezer, 5)
    assert hass_storage[STORAGE_KEY]["data"]["slots"]["default"][COVER]["changed_at"] is None
    # Auch direkte Aufrufe nach dem Stopp planen nichts mehr ein
    manager.async_update_settings(manager.settings)
    manager.async_forget(None, None)
    assert manager._unsub_timer is None
    await wait(hass, freezer, 5)
    assert hass_storage[STORAGE_KEY]["data"]["slots"]["default"][COVER]["changed_at"] is None


async def test_diagnostics(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    home.cover(70)
    data = await async_get_config_entry_diagnostics(hass, setup)
    item = data["slots"]["default"][COVER]
    assert item["would_skip"] == {"reason": "manual", "detail": "current_position: 40 → 70"}
    assert item["current"]["attributes"]["current_position"] == 70
    assert item["contexts"] == 1


async def _check(hass: HomeAssistant, config: dict[str, Any]) -> bool | None:
    validated = await condition.async_validate_condition_config(hass, config)
    checker = await condition.async_from_config(hass, validated)
    return checker(hass)


async def test_condition(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    cfg = {"condition": "recall.is_saved", "target": {"entity_id": COVER}, "options": {"slot": "tv"}}
    unchanged = {**cfg, "options": {"slot": "tv", "unchanged": True}}
    assert await _check(hass, cfg) is False
    await automation(hass, 40, slot="tv")
    await wait(hass, freezer, 16)
    assert await _check(hass, cfg) is True
    assert await _check(hass, unchanged) is True
    home.cover(80)
    await hass.async_block_till_done()
    assert await _check(hass, cfg) is True
    assert await _check(hass, unchanged) is False
    assert await _check(hass, {**cfg, "target": {"entity_id": [COVER, LIGHT]}}) is False
    assert await _check(hass, {**cfg, "target": {"area_id": "nirgends"}}) is False
    await hass.config_entries.async_unload(setup.entry_id)
    assert await _check(hass, cfg) is False


async def test_sensor_attributes(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await call(hass, "save", Context(), entity_id=COVER, slot="b", expires_after={"hours": 1})
    attrs = hass.states.get("sensor.recall_saved_states").attributes["slots"]["b"][COVER]
    assert attrs["saved_state"] == "open" and attrs["settled"] is False and attrs["expected_state"] is None
    assert attrs["expires_at"] and attrs["changed_manually"] is False and attrs["changed_by"] is None
    freezer.tick(61)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.recall_saved_states").attributes["slots"]["b"][COVER]["expected_state"] == "open"
