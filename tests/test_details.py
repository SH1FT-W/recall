"""1.2: Speichern beim Entladen, nicht unterstützte Domänen, Licht-Farbmodus, Gruppen, Rennen, Kleinigkeiten."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import condition, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from common import COVER, LIGHT, FakeHome, automation, call, wait
from custom_components.recall.const import DOMAIN, STORAGE_KEY
from custom_components.recall.diagnostics import async_get_config_entry_diagnostics

SENSOR = "sensor.recall_saved_states"


async def test_unload_flushes(hass: HomeAssistant, home: FakeHome, setup, hass_storage: dict[str, Any]) -> None:
    await call(hass, "save", entity_id=COVER, slot="a")
    assert STORAGE_KEY not in hass_storage  # noch verzögert
    await hass.config_entries.async_unload(setup.entry_id)
    assert COVER in hass_storage[STORAGE_KEY]["data"]["slots"]["a"]


async def test_remove_leaves_no_late_write(
    hass: HomeAssistant, home: FakeHome, setup, hass_storage: dict[str, Any], freezer
) -> None:
    await call(hass, "save", entity_id=COVER)
    await hass.config_entries.async_remove(setup.entry_id)
    await hass.async_block_till_done()
    await wait(hass, freezer, 10)  # ein alter Termin würde die Datei jetzt wieder anlegen
    assert STORAGE_KEY not in hass_storage


async def test_unload_clears_saver_issue(hass: HomeAssistant, home: FakeHome) -> None:
    MockConfigEntry(domain="saver", data={}).add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "saver_installed")
    await hass.config_entries.async_unload(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "saver_installed") is None


async def test_unsupported_domain(hass: HomeAssistant, home: FakeHome, setup) -> None:
    hass.states.async_set("sensor.temperatur", "21")
    hass.states.async_set("gibtsnicht.ding", "an")
    await call(hass, "save", entity_id=["sensor.temperatur", "gibtsnicht.ding", COVER])
    home.cover(30)
    result = await call(hass, "restore", only_if_unchanged=False)
    assert result["restored"] == [COVER]
    assert [(s["entity_id"], s["reason"]) for s in result["skipped"]] == [
        ("gibtsnicht.ding", "unsupported"),
        ("sensor.temperatur", "unsupported"),
    ]
    assert setup.runtime_data.slots == {}
    await call(hass, "save", entity_id="sensor.temperatur")
    result = await call(hass, "restore", forget=False)
    assert result["skipped"][0]["reason"] == "unsupported" and setup.runtime_data.count == 1


async def test_light_color_mode_without_attribute(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    home.light(True, 80, color_mode="color_temp", color_temp_kelvin=None)
    ctx = Context(parent_id="t")
    await call(hass, "save", ctx, entity_id=LIGHT)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT, "brightness": 255}, blocking=True, context=ctx
    )
    await wait(hass, freezer, 16)
    with patch("homeassistant.components.light.reproduce_state._LOGGER") as log:
        result = await call(hass, "restore")
    assert result["restored"] == [LIGHT]
    assert home.calls[-1] == ("light.turn_on", {"entity_id": LIGHT, "brightness": 80})
    assert hass.states.get(LIGHT).attributes["brightness"] == 80
    assert not log.warning.called


async def test_old_style_group_same_everywhere(hass: HomeAssistant, home: FakeHome, setup) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set("group.jalousien", "open", {"entity_id": [COVER]})
    assert (await call(hass, "save", entity_id="group.jalousien", slot="g"))["saved"] == [COVER]
    cfg = {"condition": "recall.is_saved", "target": {"entity_id": "group.jalousien"}, "options": {"slot": "g"}}
    checker = await condition.async_from_config(hass, await condition.async_validate_condition_config(hass, cfg))
    assert checker(hass) is True
    assert (await call(hass, "restore", entity_id="group.jalousien", slot="g"))["restored"] == [COVER]


async def test_parallel_restore_no_double_events(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    restored = async_capture_events(hass, "recall_restored")
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    first, second = await asyncio.gather(call(hass, "restore"), call(hass, "restore"))
    assert first["restored"] == [COVER]
    assert second["restored"] == [] and second["skipped"][0]["reason"] == "not_saved"
    assert len(restored) == 1


async def test_save_during_restore_is_kept(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Ein paralleles save ersetzt den Snapshot, während restore wartet: der neue bleibt."""
    await automation(hass, 40)
    await wait(hass, freezer, 16)

    async def save_again() -> None:
        home.hook = None
        await call(hass, "save", entity_id=COVER)

    home.hook = save_again
    await call(hass, "restore")
    snap = setup.runtime_data.get("default", COVER)
    assert snap is not None and snap.saved["attributes"]["current_position"] == 40


async def test_validation_error_passes_through(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await call(hass, "save", entity_id=COVER)
    home.cover(30)
    home.invalid = True
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "restore", only_if_unchanged=False)
    assert str(err.value) == "Position ungültig"


async def test_removed_entity_is_forgotten(hass: HomeAssistant, home: FakeHome, setup) -> None:
    forgotten = async_capture_events(hass, "recall_forgotten")
    reg = er.async_get(hass)
    markise = reg.async_get_or_create("cover", "test", "markise", suggested_object_id="markise").entity_id
    hass.states.async_set(markise, "open", {"current_position": 100})
    await call(hass, "save", entity_id=[markise, LIGHT], slot="a")
    await call(hass, "save", entity_id=markise, slot="b")
    reg.async_remove(markise)
    await hass.async_block_till_done()
    assert list(setup.runtime_data.slots) == ["a"] and list(setup.runtime_data.slots["a"]) == [LIGHT]
    assert {e.data["reason"] for e in forgotten} == {"entity_removed"}


async def test_changed_while_down_is_unknown(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    await hass.config_entries.async_unload(setup.entry_id)
    home.cover(70)
    assert await hass.config_entries.async_setup(setup.entry_id)
    await hass.async_block_till_done()
    attrs = hass.states.get(SENSOR).attributes["slots"]["default"][COVER]
    assert attrs["changed_manually"] is True and attrs["changed_by"] == "unknown"
    assert (await call(hass, "restore"))["skipped"][0]["changed_by"] == "unknown"


async def test_interrupted_during_travel(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Eingriff während der eigenen Fahrt: Detail nennt, wo es stehen blieb (nicht den Ursprungswert)."""
    ctx = Context(parent_id="t")
    await call(hass, "save", ctx, entity_id=COVER)
    home.cover(80, "closing", context=ctx)
    await hass.async_block_till_done()
    home.cover(70, context=Context(user_id="user"))
    await hass.async_block_till_done()
    snap = setup.runtime_data.get("default", COVER)
    assert snap.changed_by == "user" and snap.changed_detail == "interrupted while moving, now 70 %"
    result = await call(hass, "restore")
    assert result["skipped"][0]["detail"] == "interrupted while moving, now 70 %"


async def test_diagnostics_redacted(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    hass.states.async_set(
        "media_player.tv", "on", {"entity_picture": "/api/x?token=geheim", "access_token": "geheim", "latitude": 52.1}
    )
    await call(hass, "save", entity_id="media_player.tv")
    data = await async_get_config_entry_diagnostics(hass, setup)
    item = data["slots"]["default"]["media_player.tv"]
    for part in ("saved", "candidate", "current"):
        # Solche Attribute werden gar nicht mehr gemerkt (Allowlist je Domäne), nicht nur geschwärzt
        assert item[part]["attributes"] == {}
    assert data["options"] == {}
    assert "geheim" not in str(data)
    # Alte Speicherstände mit allen Attributen werden weiterhin geschwärzt
    setup.runtime_data.get("default", "media_player.tv").saved["attributes"] = {"access_token": "geheim"}
    data = await async_get_config_entry_diagnostics(hass, setup)
    assert data["slots"]["default"]["media_player.tv"]["saved"]["attributes"]["access_token"] == "**REDACTED**"
    assert "geheim" not in str(data)


async def test_sensor_shows_what(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    home.light(True, 204, color_mode="color_temp", color_temp_kelvin=2700)
    await call(hass, "save", entity_id=LIGHT, expires_after={"hours": 1})
    attrs = hass.states.get(SENSOR).attributes["slots"]["default"][LIGHT]
    assert attrs["saved"] == "on · 80 % · 2700 K" and attrs["expires_at"]
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "saved"})
    assert "spots: on · 80 % · 2700 K ⏳" in result["description_placeholders"]["overview"]


async def test_sensor_times_local_24h(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-16 15:59:55.295213+00:00")
    home.light(True, 204)
    await call(hass, "save", entity_id=LIGHT, expires_after={"hours": 12})
    attrs = hass.states.get(SENSOR).attributes["slots"]["default"][LIGHT]
    assert attrs["saved_at"] == "2026-10-16 17:59:55+02:00"
    assert attrs["expires_at"] == "2026-10-17 05:59:55+02:00"


async def test_only_needed_attributes_are_saved(hass: HomeAssistant, home: FakeHome, setup) -> None:
    """Speicherwachstum: je Domäne nur, was Vergleich und Wiederherstellung brauchen."""
    home.light(
        True,
        204,
        color_mode="color_temp",
        color_temp_kelvin=2700,
        friendly_name="Spots",
        supported_color_modes=["color_temp", "hs"],
        icon="mdi:spotlight",
        effect_list=["a", "b"],
    )
    hass.states.async_set(
        "media_player.tv",
        "playing",
        {"volume_level": 0.4, "is_volume_muted": False, "source": "HDMI", "media_position": 12, "media_title": "x"},
    )
    hass.states.async_set("switch.steckdose", "on", {"friendly_name": "Steckdose", "icon": "mdi:power"})
    await call(hass, "save", entity_id=[LIGHT, "media_player.tv", "switch.steckdose"])
    manager = setup.runtime_data
    assert manager.get("default", LIGHT).saved["attributes"] == {
        "brightness": 204,
        "color_mode": "color_temp",
        "color_temp_kelvin": 2700,
    }
    assert manager.get("default", "media_player.tv").saved["attributes"] == {
        "volume_level": 0.4,
        "is_volume_muted": False,
        "source": "HDMI",
    }
    assert manager.get("default", "switch.steckdose").saved["attributes"] == {}


async def test_position_updates_cause_no_writes(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Medienplayer melden ständig neue Positionen: das darf weder speichern noch den Sensor schreiben."""
    tv = "media_player.tv"
    hass.states.async_set(tv, "playing", {"volume_level": 0.4, "media_position": 0})
    await call(hass, "save", entity_id=tv)
    manager = setup.runtime_data
    with patch.object(manager._store, "async_delay_save", wraps=manager._store.async_delay_save) as delay_save:
        # Noch beim Beruhigen: nur das Ruhefenster wandert (kein gespeichertes Feld ändert sich)
        hass.states.async_set(tv, "playing", {"volume_level": 0.4, "media_position": 5})
        await hass.async_block_till_done()
        assert delay_save.call_count == 0
        await wait(hass, freezer, 16)  # erwarteter Zustand steht
        assert manager.get("default", tv).settled
        delay_save.reset_mock()
        sensor_before = hass.states.get(SENSOR)
        for position in range(10, 60, 10):
            hass.states.async_set(tv, "playing", {"volume_level": 0.4, "media_position": position})
            await hass.async_block_till_done()
        assert delay_save.call_count == 0
        assert hass.states.get(SENSOR).last_reported == sensor_before.last_reported
        # Eine echte Abweichung wird weiterhin sofort gespeichert
        hass.states.async_set(tv, "playing", {"volume_level": 0.9, "media_position": 70})
        await hass.async_block_till_done()
        assert delay_save.call_count == 1
        assert hass.states.get(SENSOR).attributes["slots"]["default"][tv]["changed_manually"] is True


async def test_unload_skips_write_after_delayed_save(
    hass: HomeAssistant, home: FakeHome, setup, hass_storage: dict[str, Any], freezer
) -> None:
    """Hat das verzögerte Speichern schon geschrieben, schreibt das Entladen nicht noch einmal."""
    await call(hass, "save", entity_id=COVER, slot="a")
    await wait(hass, freezer, 10)
    assert COVER in hass_storage[STORAGE_KEY]["data"]["slots"]["a"]
    hass_storage.pop(STORAGE_KEY)
    await hass.config_entries.async_unload(setup.entry_id)
    assert STORAGE_KEY not in hass_storage
