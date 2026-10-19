"""Kern: merken, beruhigen, Handbetrieb erkennen, wiederherstellen, Slots, Ablauf."""

from __future__ import annotations

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from common import COVER, LIGHT, FakeHome, automation, call, wait

SENSOR = "sensor.recall_saved_states"


def snap(entry: MockConfigEntry, slot: str = "default", entity_id: str = COVER):
    return entry.runtime_data.get(slot, entity_id)


async def test_save_restore(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    saved = async_capture_events(hass, "recall_saved")
    restored = async_capture_events(hass, "recall_restored")
    await automation(hass, 40)
    assert hass.states.get(SENSOR).state == "1"
    assert saved[0].data == {"slot": "default", "entity_id": [COVER]}
    await wait(hass, freezer, 16)
    assert snap(setup).settled and snap(setup).expected["attributes"]["current_position"] == 40

    result = await call(hass, "restore", entity_id=COVER)
    await hass.async_block_till_done()
    assert result == {"slot": "default", "restored": [COVER], "skipped": []}
    assert home.calls[-1] == ("cover.set_cover_position", {"entity_id": COVER, "position": 100})
    assert hass.states.get(COVER).attributes["current_position"] == 100
    assert restored[0].data["entity_id"] == [COVER]
    assert snap(setup) is None
    assert hass.states.get(SENSOR).state == "0"


async def test_manual_change_skips(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    skipped = async_capture_events(hass, "recall_skipped")
    forgotten = async_capture_events(hass, "recall_forgotten")
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    home.cover(70)  # Taster an der Wand
    await hass.async_block_till_done()
    attrs = hass.states.get(SENSOR).attributes["slots"]["default"][COVER]
    assert attrs["changed_manually"] is True and attrs["changed_by"] == "device"
    assert attrs["expected_state"] == "open" and attrs["settled"] is True

    calls = len(home.calls)
    result = await call(hass, "restore")
    assert result["restored"] == []
    assert result["skipped"] == [
        {"entity_id": COVER, "reason": "manual", "detail": "current_position: 40 → 70", "changed_by": "device"}
    ]
    assert len(home.calls) == calls
    assert skipped[0].data["reason"] == "manual"
    assert forgotten[0].data["reason"] == "restore"
    assert snap(setup) is None


async def test_within_tolerance_is_not_manual(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40, tolerance=3)
    await wait(hass, freezer, 16)
    home.cover(42)  # Motor nachjustiert
    await hass.async_block_till_done()
    result = await call(hass, "restore")
    assert result["restored"] == [COVER]


async def test_travel_is_not_manual(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Zwischenstände der eigenen Fahrt (auch ohne Kontext gemeldet) zählen nie als Handbetrieb."""
    ctx = Context(parent_id="trigger")
    await call(hass, "save", ctx, entity_id=COVER)
    home.cover(90, "closing", context=ctx)
    await wait(hass, freezer, 10)
    home.cover(60, "closing")
    await wait(hass, freezer, 10)
    home.cover(30, "closing")
    await wait(hass, freezer, 30)  # bleibt in Fahrt: nicht fertig
    assert not snap(setup).settled
    home.cover(20)
    await wait(hass, freezer, 16)
    assert snap(setup).expected["attributes"]["current_position"] == 20
    assert (await call(hass, "restore"))["restored"] == [COVER]


async def test_moving_at_restore(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    home.cover(55, "opening")
    await hass.async_block_till_done()
    result = await call(hass, "restore", forget=False)
    assert result["skipped"][0]["reason"] == "moving"
    assert snap(setup) is not None  # forget=False behält es


async def test_force_restore(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    home.cover(70)
    await hass.async_block_till_done()
    result = await call(hass, "restore", only_if_unchanged=False)
    assert result["restored"] == [COVER]


async def test_back_to_expected_is_unchanged(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    home.cover(70)
    await hass.async_block_till_done()
    assert snap(setup).changed_at is not None
    home.cover(40)
    await hass.async_block_till_done()
    assert snap(setup).changed_at is None
    assert (await call(hass, "restore"))["restored"] == [COVER]


async def test_user_during_settling(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Bedienung in HA, bevor die Automation zur Ruhe kam: erwartet ist der letzte ruhige Zustand."""
    await automation(hass, 40)
    await wait(hass, freezer, 3)
    home.cover(80, context=Context(user_id="user"))
    await hass.async_block_till_done()
    s = snap(setup)
    assert s.settled and s.expected["attributes"]["current_position"] == 40
    assert s.changed_by == "user"
    result = await call(hass, "restore")
    assert result["skipped"][0]["reason"] == "manual"


async def test_other_automation_after_settle(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": COVER, "position": 0},
        blocking=True,
        context=Context(parent_id="x"),
    )
    assert snap(setup).changed_by == "automation"


async def test_own_later_step_relearns(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Die merkende Automation fährt nach einer Verzögerung weiter: neuer erwarteter Zustand, kein Handbetrieb."""
    ctx = await automation(hass, 40)
    await wait(hass, freezer, 120)
    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": COVER, "position": 20}, blocking=True, context=ctx
    )
    assert not snap(setup).settled
    await wait(hass, freezer, 16)
    assert snap(setup).expected["attributes"]["current_position"] == 20
    assert (await call(hass, "restore"))["restored"] == [COVER]


async def test_nothing_changes(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await call(hass, "save", entity_id=COVER)
    await wait(hass, freezer, 30)
    assert not snap(setup).settled
    await wait(hass, freezer, 31)
    assert snap(setup).settled and snap(setup).expected["attributes"]["current_position"] == 100


async def test_never_settles_uses_last_stable(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    ctx = Context(parent_id="t")
    await call(hass, "save", ctx, entity_id=COVER)
    home.cover(50, context=ctx)
    await hass.async_block_till_done()
    home.cover(45, "closing")
    for _ in range(45):
        await wait(hass, freezer, 15)
    assert snap(setup).settled
    assert snap(setup).expected["attributes"]["current_position"] == 50


async def test_unavailable_while_settling(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    hass.states.async_set(COVER, "unavailable", {})
    await wait(hass, freezer, 16)
    assert not snap(setup).settled  # „nicht verfügbar“ wird nie als erwarteter Zustand gelernt
    result = await call(hass, "restore", forget=False)
    assert result["skipped"] == [{"entity_id": COVER, "reason": "unavailable", "detail": None, "changed_by": None}]
    assert snap(setup) is not None


async def test_unavailable_at_settle_time(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await call(hass, "save", entity_id=COVER)
    hass.states.async_set(COVER, "unavailable", {})
    await wait(hass, freezer, 61)
    assert not snap(setup).settled
    home.cover(100)
    await wait(hass, freezer, 16)
    assert snap(setup).settled


async def test_slots_are_independent(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40, slot="apple_tv")
    await wait(hass, freezer, 16)
    await automation(hass, 20, slot="ps5")
    await wait(hass, freezer, 16)
    assert hass.states.get(SENSOR).state == "2"
    # PS5 zurück → 40 = erwarteter Zustand von Apple TV → Apple TV darf danach auf 100
    assert (await call(hass, "restore", slot="ps5"))["restored"] == [COVER]
    await hass.async_block_till_done()
    assert hass.states.get(COVER).attributes["current_position"] == 40
    assert snap(setup, "apple_tv").changed_at is None
    assert (await call(hass, "restore", slot="apple_tv"))["restored"] == [COVER]
    assert hass.states.get(COVER).attributes["current_position"] == 100


async def test_overwrite_false_keeps_original(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 100)
    home.cover(30)
    await hass.async_block_till_done()
    await wait(hass, freezer, 61)
    ctx = Context(parent_id="t2")
    result = await call(hass, "save", ctx, entity_id=COVER, overwrite=False)
    assert result == {"slot": "default", "saved": [], "kept": [COVER], "missing": []}
    assert snap(setup).saved["attributes"]["current_position"] == 100
    result = await call(hass, "save", entity_id=COVER)
    assert result["saved"] == [COVER]
    assert snap(setup).saved["attributes"]["current_position"] == 30


async def test_expires(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    forgotten = async_capture_events(hass, "recall_forgotten")
    await call(hass, "save", entity_id=COVER, expires_after={"minutes": 5})
    assert snap(setup).expires_at is not None
    await wait(hass, freezer, 61)
    await wait(hass, freezer, 240)
    assert snap(setup) is None
    assert forgotten[0].data == {"slot": "default", "entity_id": [COVER], "reason": "expired"}


async def test_overwrite_false_renews_expiry(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await call(hass, "save", entity_id=COVER, expires_after={"minutes": 5})
    first = snap(setup).expires_at
    await wait(hass, freezer, 60)
    await call(hass, "save", entity_id=COVER, overwrite=False, expires_after={"minutes": 5})
    assert snap(setup).expires_at > first


async def test_restore_without_forget_relearns(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await automation(hass, 40)
    await wait(hass, freezer, 16)
    await call(hass, "restore", forget=False)
    await wait(hass, freezer, 16)
    assert snap(setup).expected["attributes"]["current_position"] == 100
    assert snap(setup).changed_at is None


async def test_restore_subset_and_not_saved(hass: HomeAssistant, home: FakeHome, setup) -> None:
    result = await call(hass, "restore", entity_id=[COVER, LIGHT])
    assert [s["reason"] for s in result["skipped"]] == ["not_saved", "not_saved"]
    result = await call(hass, "restore", slot="leer")
    assert result["restored"] == [] and result["skipped"] == [
        {"entity_id": None, "reason": "not_saved", "detail": "slot leer is empty", "changed_by": None}
    ]


async def test_light_transition(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    home.light(True, 80)
    ctx = Context(parent_id="t")
    await call(hass, "save", ctx, entity_id=LIGHT)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT, "brightness": 255}, blocking=True, context=ctx
    )
    await wait(hass, freezer, 16)
    await call(hass, "restore", transition=3)
    assert home.calls[-1] == ("light.turn_on", {"entity_id": LIGHT, "brightness": 80, "transition": 3.0})


async def test_area_target(hass: HomeAssistant, home: FakeHome, setup) -> None:
    from homeassistant.helpers import area_registry as ar, entity_registry as er

    area = ar.async_get(hass).async_create("Flur")
    reg = er.async_get(hass)
    entry = reg.async_get_or_create("light", "test", "flur", suggested_object_id="flur")
    reg.async_update_entity(entry.entity_id, area_id=area.id)
    hass.states.async_set("light.flur", "on", {"brightness": 40})
    result = await call(hass, "save", area_id=area.id)
    assert result["saved"] == ["light.flur"]


async def test_restore_failed(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await call(hass, "save", entity_id=COVER)
    home.cover(30)
    home.fail = True
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "restore", only_if_unchanged=False)
    assert err.value.translation_key == "restore_failed"
    assert snap(setup) is not None


async def test_forget(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await call(hass, "save", entity_id=[COVER, LIGHT], slot="a")
    await call(hass, "save", entity_id=COVER, slot="b")
    assert await call(hass, "forget", entity_id=COVER) == {"forgotten": {"a": [COVER], "b": [COVER]}}
    assert await call(hass, "forget", slot="a") == {"forgotten": {"a": [LIGHT]}}
    assert await call(hass, "forget", slot="a") == {"forgotten": {}, "skipped": [{"slot": "a", "reason": "not_saved"}]}
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "forget")
    assert err.value.translation_key == "forget_nothing"


async def test_save_errors(hass: HomeAssistant, home: FakeHome, setup) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "save", entity_id="none")
    assert err.value.translation_key == "no_entities"
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "save", entity_id="cover.gibt_es_nicht")
    assert err.value.translation_key == "nothing_saved"
    result = await call(hass, "save", entity_id=[COVER, "cover.gibt_es_nicht"])
    assert result["missing"] == ["cover.gibt_es_nicht"]


async def test_not_loaded(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await hass.config_entries.async_unload(setup.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "save", entity_id=COVER)
    assert err.value.translation_key == "not_loaded"


async def test_entity_removed_is_ignored(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await call(hass, "save", entity_id=COVER)
    hass.states.async_remove(COVER)
    await hass.async_block_till_done()
    assert snap(setup) is not None
