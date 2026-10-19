"""Mit HAs echter Demo-Jalousie (fährt 10 % pro Sekunde, meldet opening/closing) statt Fake-Gerät."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from homeassistant.components.demo.cover import DemoCover
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from common import call, wait
from custom_components.recall.const import DOMAIN

HALL = "cover.hall_window"


@pytest.fixture
async def demo(hass: HomeAssistant) -> AsyncIterator[None]:
    """Demo-Jalousie über einen Konfigurationseintrag (wie heute üblich, keine YAML-Plattform)."""

    async def setup_cover(hass: HomeAssistant, entry: ConfigEntry, add_entities: Any) -> None:
        add_entities([DemoCover(hass, "cover_2", "Hall Window", 10)])

    async def setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.COVER])
        return True

    mock_integration(hass, MockModule("fake_demo", async_setup_entry=setup_entry))
    mock_platform(hass, "fake_demo.config_flow")
    flow = mock_config_flow("fake_demo", DemoFlow)
    flow.__enter__()
    mock_platform(hass, "fake_demo.cover", MockPlatform(async_setup_entry=setup_cover))
    demo_entry = MockConfigEntry(domain="fake_demo", data={})
    demo_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(demo_entry.entry_id)
    await hass.async_block_till_done()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield
    flow.__exit__(None, None, None)


class DemoFlow(ConfigFlow):
    """Leerer Ablauf, damit HA den Eintrag der Demo-Integration annimmt."""

    VERSION = 1


async def move(hass: HomeAssistant, position: int, context: Context) -> None:
    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": HALL, "position": position}, blocking=True, context=context
    )


def position(hass: HomeAssistant) -> int:
    return int(hass.states.get(HALL).attributes["current_position"])


async def test_demo_cover_round_trip(hass: HomeAssistant, demo, freezer) -> None:
    assert position(hass) == 10
    ctx = Context(parent_id="apple_tv")
    await call(hass, "save", ctx, entity_id=HALL, slot="tv")
    await move(hass, 60, ctx)
    for _ in range(8):  # fährt sekundenweise, Zwischenstände „opening“ ohne Kontext
        await wait(hass, freezer, 1)
    assert position(hass) == 60
    await wait(hass, freezer, 16)
    snap = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.get("tv", HALL)
    assert snap.settled and snap.expected["attributes"]["current_position"] == 60

    result = await call(hass, "restore", slot="tv")
    assert result["restored"] == [HALL]
    for _ in range(8):
        await wait(hass, freezer, 1)
    assert position(hass) == 10


async def test_demo_cover_manual(hass: HomeAssistant, demo, freezer, hass_admin_user) -> None:
    ctx = Context(parent_id="apple_tv")
    await call(hass, "save", ctx, entity_id=HALL, slot="tv")
    await move(hass, 60, ctx)
    for _ in range(25):
        await wait(hass, freezer, 1)
    await move(hass, 30, Context(user_id=hass_admin_user.id))  # in der App verstellt
    for _ in range(5):
        await wait(hass, freezer, 1)
    result = await call(hass, "restore", slot="tv")
    assert result["skipped"] == [
        {"entity_id": HALL, "reason": "manual", "detail": "current_position: 60 → 30", "changed_by": "user"}
    ]
    assert position(hass) == 30
