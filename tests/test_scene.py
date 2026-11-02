"""recall.create_scene: a dynamic scene (scene.create) from a remembered slot."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest

from common import COVER, LIGHT, FakeHome, call


@pytest.fixture
async def scenes(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()


async def test_create_scene_from_slot(hass: HomeAssistant, home: FakeHome, setup, scenes) -> None:
    home.cover(70, current_tilt_position=30)
    home.light(True, 128, color_mode="color_temp", color_temp_kelvin=2700, friendly_name="Spots")
    await call(hass, "save", entity_id=[COVER, LIGHT], slot="Movie Night")

    result = await call(hass, "create_scene", slot="Movie Night")
    assert result == {
        "slot": "Movie Night",
        "scene": "scene.recall_movie_night",
        "entity_id": [COVER, LIGHT],
        "skipped": [],
    }
    scene = hass.states.get("scene.recall_movie_night")
    assert scene is not None and sorted(scene.attributes["entity_id"]) == [COVER, LIGHT]
    assert setup.runtime_data.count == 2  # the slot stays

    home.cover(0)
    home.light(False)
    await hass.services.async_call("scene", "turn_on", {"entity_id": "scene.recall_movie_night"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(COVER).attributes["current_position"] == 70
    light = hass.states.get(LIGHT)
    assert light.state == "on" and light.attributes["brightness"] == 128
    assert light.attributes["color_temp_kelvin"] == 2700
    # Only the attributes reproduce_state reads go into the scene (no friendly_name, supported_features)
    assert ("light.turn_on", {"entity_id": LIGHT, "brightness": 128, "color_temp_kelvin": 2700}) in home.calls


async def test_scene_id_and_entities(hass: HomeAssistant, home: FakeHome, setup, scenes) -> None:
    await call(hass, "save", entity_id=[COVER, LIGHT], slot="evening")
    result = await call(hass, "create_scene", slot="evening", scene_id="blinds_only", entity_id=[COVER, "cover.nope"])
    assert result["scene"] == "scene.recall_blinds_only" and result["entity_id"] == [COVER]
    assert result["skipped"] == [{"entity_id": "cover.nope", "reason": "not_saved", "detail": None, "changed_by": None}]
    assert hass.states.get("scene.recall_blinds_only").attributes["entity_id"] == [COVER]
    assert hass.states.get("scene.recall_evening") is None

    # Calling again replaces the dynamic scene
    result = await call(hass, "create_scene", slot="evening", scene_id="recall_blinds_only")  # prefix is not doubled
    assert sorted(hass.states.get("scene.recall_blinds_only").attributes["entity_id"]) == [COVER, LIGHT]


async def test_unsupported_domain_left_out(hass: HomeAssistant, home: FakeHome, setup, scenes) -> None:
    hass.states.async_set("sensor.temperature", "21")
    await call(hass, "save", entity_id=["sensor.temperature", COVER])
    result = await call(hass, "create_scene")
    assert result["scene"] == "scene.recall_default" and result["entity_id"] == [COVER]
    assert [(s["entity_id"], s["reason"]) for s in result["skipped"]] == [("sensor.temperature", "unsupported")]


async def test_empty_slot(hass: HomeAssistant, home: FakeHome, setup, scenes) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "create_scene", slot="nothing")
    assert err.value.translation_key == "scene_empty"
    hass.states.async_set("sensor.temperature", "21")
    await call(hass, "save", entity_id="sensor.temperature", slot="sensors")
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "create_scene", slot="sensors")
    assert err.value.translation_key == "scene_empty"


async def test_without_scene_integration(hass: HomeAssistant, home: FakeHome, setup) -> None:
    await call(hass, "save", entity_id=COVER)
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "create_scene")
    assert err.value.translation_key == "scene_unavailable"


async def test_own_namespace(hass: HomeAssistant, home: FakeHome, setup) -> None:
    """A scene of the same name from scenes.yaml (or Hue & Co.) stays untouched: Recall uses scene.recall_…."""
    assert await async_setup_component(hass, "scene", {"scene": [{"name": "Evening", "entities": {LIGHT: "on"}}]})
    await hass.async_block_till_done()
    await call(hass, "save", entity_id=COVER, slot="evening")
    result = await call(hass, "create_scene", slot="evening")
    assert result["scene"] == "scene.recall_evening"
    assert hass.states.get("scene.evening").attributes["entity_id"] == [LIGHT]
    result = await call(hass, "create_scene", slot="evening", scene_id="evening")
    assert result["scene"] == "scene.recall_evening"


@pytest.mark.parametrize("scene_id", [None, "recall_living_room"])
async def test_scene_from_yaml_is_not_replaced(hass: HomeAssistant, home: FakeHome, setup, scene_id) -> None:
    config = {"name": "Recall living room", "entities": {COVER: "open"}}
    if scene_id:
        config["id"] = scene_id
    assert await async_setup_component(hass, "scene", {"scene": [config]})
    await hass.async_block_till_done()
    await call(hass, "save", entity_id=COVER, slot="living room")
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "create_scene", slot="living room")
    assert err.value.translation_key == "scene_exists"
    assert err.value.translation_placeholders == {"entity_id": "scene.recall_living_room"}


async def test_invalid_scene_id(hass: HomeAssistant, home: FakeHome, setup, scenes) -> None:
    await call(hass, "save", entity_id=COVER)
    with pytest.raises(Exception, match="slug"):
        await call(hass, "create_scene", scene_id="Not A Slug")
