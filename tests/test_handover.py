"""Übergabe zwischen Slots: Eine Automation mit eigenem Slot merkt und verstellt danach – kein Handeingriff."""

from __future__ import annotations

from itertools import permutations

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import condition
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from common import COVER, FakeHome, automation, call, wait

SENSOR = "sensor.recall_saved_states"


def position(hass: HomeAssistant) -> int:
    return int(hass.states.get(COVER).attributes["current_position"])


async def chain(hass: HomeAssistant, home: FakeHome, freezer, steps: list[tuple[str, int]]) -> None:
    """Jalousie steht auf 70; jede Automation merkt (overwrite: false) und fährt weiter, dann Ruhe."""
    home.cover(70)
    await hass.async_block_till_done()
    for slot, target in steps:
        await automation(hass, target, slot=slot, overwrite=False)
        await wait(hass, freezer, 16)


async def off(hass: HomeAssistant, freezer, slot: str) -> dict:
    result = await call(hass, "restore", slot=slot)
    await wait(hass, freezer, 16)
    return result


async def test_two_slots_ps5_first(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """PS5 70→50, Apple TV merkt 50 und fährt auf 40; PS5 aus zuerst, Apple TV aus → wieder 70."""
    skipped = async_capture_events(hass, "recall_skipped")
    forgotten = async_capture_events(hass, "recall_forgotten")
    await chain(hass, home, freezer, [("ps5", 50), ("apple_tv", 40)])
    ps5 = setup.runtime_data.get("ps5", COVER)
    assert ps5.changed_by == "recall"
    attrs = hass.states.get(SENSOR).attributes["slots"]["ps5"][COVER]
    assert attrs["changed_manually"] is False and attrs["handed_over_to"] == "apple_tv"
    assert attrs["saved"] == "70 %" and attrs["expected"] == "50 %"

    calls = len(home.calls)
    result = await off(hass, freezer, "ps5")
    assert result["restored"] == []
    assert result["skipped"] == [
        {"entity_id": COVER, "reason": "handed_over", "detail": "apple_tv", "changed_by": "recall"}
    ]
    assert len(home.calls) == calls  # ohne Bewegung
    assert position(hass) == 40
    assert setup.runtime_data.get("ps5", COVER) is None
    assert setup.runtime_data.get("apple_tv", COVER).saved["attributes"]["current_position"] == 70
    assert skipped[-1].data["reason"] == "handed_over"
    assert forgotten[-1].data == {"slot": "ps5", "entity_id": [COVER], "reason": "handed_over"}

    assert (await off(hass, freezer, "apple_tv"))["restored"] == [COVER]
    assert position(hass) == 70
    assert setup.runtime_data.slots == {}


async def test_two_slots_apple_tv_first(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await chain(hass, home, freezer, [("ps5", 50), ("apple_tv", 40)])
    assert (await off(hass, freezer, "apple_tv"))["restored"] == [COVER]
    assert position(hass) == 50
    assert setup.runtime_data.get("ps5", COVER).changed_at is None
    assert (await off(hass, freezer, "ps5"))["restored"] == [COVER]
    assert position(hass) == 70


@pytest.mark.parametrize("order", list(permutations(["a", "b", "c"])))
async def test_three_slots_every_order(hass: HomeAssistant, home: FakeHome, setup, freezer, order) -> None:
    await chain(hass, home, freezer, [("a", 50), ("b", 40), ("c", 30)])
    for slot in order:
        result = await off(hass, freezer, slot)
        assert not [s for s in result["skipped"] if s["reason"] == "manual"], result
    assert position(hass) == 70
    assert setup.runtime_data.slots == {}


async def test_real_manual_after_handover(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Nach dem Merken des zweiten Slots von Hand verstellt: Übergabe, dann erkennt der zweite den Eingriff."""
    await chain(hass, home, freezer, [("ps5", 50), ("apple_tv", 40)])
    home.cover(20)  # Taster
    await hass.async_block_till_done()
    assert (await off(hass, freezer, "ps5"))["skipped"][0]["reason"] == "handed_over"
    result = await off(hass, freezer, "apple_tv")
    assert result["skipped"][0]["reason"] == "manual" and result["skipped"][0]["changed_by"] == "device"
    assert position(hass) == 20


async def test_manual_before_second_slot(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Von Hand verstellt, bevor der zweite Slot merkt: der hat nicht unseren Zustand → echter Handeingriff."""
    home.cover(70)
    await automation(hass, 50, slot="ps5", overwrite=False)
    await wait(hass, freezer, 16)
    home.cover(60, context=Context(user_id="user"))
    await hass.async_block_till_done()
    await automation(hass, 40, slot="apple_tv", overwrite=False)
    await wait(hass, freezer, 16)
    result = await off(hass, freezer, "ps5")
    assert result["skipped"][0] == {
        "entity_id": COVER,
        "reason": "manual",
        "detail": "current_position: 50 → 40",
        "changed_by": "user",
    }
    assert (await off(hass, freezer, "apple_tv"))["restored"] == [COVER]
    assert position(hass) == 60


async def test_foreign_automation_stays_manual(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    """Fremde Automation ohne Recall-Slot: Handeingriff, erkennbar an changed_by: automation."""
    home.cover(70)
    await automation(hass, 50, slot="ps5")
    await wait(hass, freezer, 16)
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": COVER, "position": 30},
        blocking=True,
        context=Context(parent_id="x"),
    )
    result = await off(hass, freezer, "ps5")
    assert result["skipped"][0]["reason"] == "manual" and result["skipped"][0]["changed_by"] == "automation"
    assert position(hass) == 30


async def test_handover_forget_false_and_force(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    await chain(hass, home, freezer, [("ps5", 50), ("apple_tv", 40)])
    result = await call(hass, "restore", slot="ps5", forget=False)
    assert result["skipped"][0]["reason"] == "handed_over"
    assert setup.runtime_data.get("ps5", COVER) is None  # übergeben = hier vergessen

    await chain(hass, home, freezer, [("x", 50), ("y", 40)])
    assert (await call(hass, "restore", slot="x", only_if_unchanged=False))["restored"] == [COVER]


async def test_handover_counts_as_unchanged(hass: HomeAssistant, home: FakeHome, setup, freezer) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    await chain(hass, home, freezer, [("ps5", 50), ("apple_tv", 40)])
    cfg = {
        "condition": "recall.is_saved",
        "target": {"entity_id": COVER},
        "options": {"slot": "ps5", "unchanged": True},
    }
    checker = await condition.async_from_config(hass, await condition.async_validate_condition_config(hass, cfg))
    assert checker(hass) is True


async def test_saved_states_overview_shows_handover(
    hass: HomeAssistant, home: FakeHome, setup: MockConfigEntry, freezer
) -> None:
    await chain(hass, home, freezer, [("ps5", 50), ("apple_tv", 40)])
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "saved"})
    assert "jalousie: 70 % ↪ apple_tv" in result["description_placeholders"]["overview"]
