"""Fixtures: eigene Integrationen erlauben, Fake-Geräte, Recall-Eintrag."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from common import FakeHome
from custom_components.recall.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def home(hass: HomeAssistant) -> FakeHome:
    fake = FakeHome(hass)
    fake.install()
    fake.cover(100)
    fake.light(False)
    return fake


@pytest.fixture
async def setup(hass: HomeAssistant, home: FakeHome) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Recall", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
