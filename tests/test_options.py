"""Konfigurieren: Standardwerte (ohne Neustart wirksam) und gemerkte Zustände vergessen."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from common import COVER, LIGHT, FakeHome, automation, call, wait
from custom_components.recall.const import STORAGE_KEY
from custom_components.recall.settings import Settings

SETTINGS = {
    "restore": {"only_if_unchanged": False, "forget": False},
    "detection": {"tolerance": 10, "settle_quiet": 5, "settle_wait": 20, "settle_max": 2},
    "expiry": {"expires_after": {"hours": 2, "minutes": 0, "seconds": 0}},
}


async def configure(hass: HomeAssistant, entry: MockConfigEntry, data: dict[str, Any]) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["settings", "saved"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "settings"
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result


def test_defaults_from_const() -> None:
    settings = Settings.from_options({})
    assert settings == Settings()
    assert settings.only_if_unchanged and settings.forget and settings.tolerance == 3
    assert settings.settle_quiet == timedelta(seconds=15) and settings.settle_max == timedelta(minutes=10)
    assert settings.expires_after is None
    assert Settings.from_options({"expiry": {"expires_after": "kaputt"}}).expires_after is None
    assert Settings.from_options({"expiry": {"expires_after": {"minutes": 0}}}).expires_after is None


async def test_settings_apply_without_restart(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await configure(hass, setup, SETTINGS)
    manager = setup.runtime_data
    assert manager.settings.tolerance == 10 and manager.settings.expires_after == timedelta(hours=2)

    await automation(hass, 40)
    snap = manager.get("default", COVER)
    assert snap.tolerance == 10
    assert snap.expires_at - snap.saved_at == timedelta(hours=2)
    await wait(hass, freezer, 6)  # Ruhezeit 5 s statt 15 s
    assert snap.settled
    home.cover(70)
    await hass.async_block_till_done()
    # Handeingriff ignorieren + nicht vergessen kommen aus den Optionen
    result = await call(hass, "restore")
    assert result["restored"] == [COVER]
    assert manager.get("default", COVER) is not None
    # Aktion überschreibt die Optionen; 0 = nie verfallen
    result = await call(hass, "save", entity_id=LIGHT, slot="x", expires_after=0, tolerance=1)
    light = manager.get("x", LIGHT)
    assert light.expires_at is None and light.tolerance == 1


async def test_settings_form_keeps_values(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await configure(hass, setup, SETTINGS)
    assert setup.options["expiry"]["expires_after"]["hours"] == 2
    off = {**SETTINGS, "expiry": {"expires_after": {"hours": 0, "minutes": 0, "seconds": 0}}}
    await configure(hass, setup, off)
    assert setup.options["expiry"] == {}
    assert setup.runtime_data.settings.expires_after is None
    await configure(hass, setup, {**SETTINGS, "expiry": {}})
    assert setup.runtime_data.settings.settle_wait == timedelta(seconds=20)


async def test_settle_wait_option(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await configure(hass, setup, SETTINGS)
    await call(hass, "save", entity_id=COVER)
    await wait(hass, freezer, 21)
    assert setup.runtime_data.get("default", COVER).settled


async def test_saved_states_forget(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "saved"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "nothing_saved"

    await automation(hass, 40, slot="apple_tv")
    await wait(hass, freezer, 16)
    home.cover(70)
    await call(hass, "save", entity_id=LIGHT, slot="licht")
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "saved"})
    assert result["type"] is FlowResultType.FORM
    overview = result["description_placeholders"]["overview"]
    assert "- **apple_tv**\n  - jalousie: 100 % ✋" in overview and "**licht**\n  - spots: off" in overview
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"slots": ["apple_tv"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert list(setup.runtime_data.slots) == ["licht"]


async def test_saved_states_not_loaded(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await hass.config_entries.async_unload(setup.entry_id)
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "saved"})
    assert result["reason"] == "not_loaded"


async def test_entity_without_state_in_overview(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await call(hass, "save", entity_id=COVER, slot="weg")
    hass.states.async_remove(COVER)
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "saved"})
    assert COVER in result["description_placeholders"]["overview"]


async def test_settings_change_writes_nothing(
    hass: HomeAssistant, home: FakeHome, setup, freezer, hass_storage: dict[str, Any]
) -> None:
    """Optionen ändern nur Vorgaben, nicht das Gemerkte: kein Schreibvorgang in .storage."""
    await call(hass, "save", entity_id=COVER)
    await wait(hass, freezer, 10)
    hass_storage.pop(STORAGE_KEY)
    await configure(hass, setup, SETTINGS)
    await wait(hass, freezer, 10)
    assert STORAGE_KEY not in hass_storage
    assert setup.runtime_data.settings.tolerance == 10
