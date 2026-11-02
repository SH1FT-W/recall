"""Actions recall.save / restore / forget / create_scene (registered in async_setup, with response data)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import slugify
import voluptuous as vol

from .const import (
    ATTR_EXPIRES_AFTER,
    ATTR_FORGET,
    ATTR_ONLY_IF_UNCHANGED,
    ATTR_OVERWRITE,
    ATTR_SCENE_ID,
    ATTR_SLOT,
    ATTR_TOLERANCE,
    ATTR_TRANSITION,
    DEFAULT_SLOT,
    DOMAIN,
)
from .manager import resolve_targets

if TYPE_CHECKING:
    from .manager import RecallManager

SERVICE_SAVE = "save"
SERVICE_RESTORE = "restore"
SERVICE_FORGET = "forget"
SERVICE_CREATE_SCENE = "create_scene"

SCENE_DOMAIN = "scene"
SCENE_SERVICE_CREATE = "create"
SCENE_PREFIX = f"{DOMAIN}_"

SLOT = vol.All(cv.string, vol.Strip, vol.Length(min=1, max=64))

SAVE_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_SLOT, default=DEFAULT_SLOT): SLOT,
        vol.Optional(ATTR_EXPIRES_AFTER): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(ATTR_OVERWRITE, default=True): cv.boolean,
        vol.Optional(ATTR_TOLERANCE): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)
RESTORE_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_SLOT, default=DEFAULT_SLOT): SLOT,
        vol.Optional(ATTR_ONLY_IF_UNCHANGED): cv.boolean,
        vol.Optional(ATTR_FORGET): cv.boolean,
        vol.Optional(ATTR_TRANSITION): vol.All(vol.Coerce(float), vol.Range(min=0, max=6553)),
    }
)
FORGET_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_SLOT): SLOT,
    }
)
CREATE_SCENE_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_SLOT, default=DEFAULT_SLOT): SLOT,
        vol.Optional(ATTR_SCENE_ID): cv.slug,
    }
)


def get_manager(hass: HomeAssistant) -> RecallManager:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    manager: RecallManager = entries[0].runtime_data
    return manager


def _targets(hass: HomeAssistant, call: ServiceCall) -> list[str] | None:
    """Ziel-Entitäten (Entität, Gerät, Bereich, Etage, Label); None = kein Ziel angegeben."""
    if not any(call.data.get(str(key)) for key in cv.ENTITY_SERVICE_FIELDS):
        return None
    return sorted(resolve_targets(hass, call.data))


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def save(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        entity_ids = _targets(hass, call)
        if not entity_ids:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_entities")
        settings = manager.settings
        # Leer = Standard aus den Optionen, 0 = in diesem Aufruf nie verfallen
        expires = call.data.get(ATTR_EXPIRES_AFTER, settings.expires_after)
        result: dict[str, Any] = manager.async_save(
            call.data[ATTR_SLOT],
            entity_ids,
            context=call.context,
            expires_after=expires or None,
            overwrite=call.data[ATTR_OVERWRITE],
            tolerance=call.data.get(ATTR_TOLERANCE, settings.tolerance),
        )
        if not result["saved"] and not result["kept"]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="nothing_saved",
                translation_placeholders={ATTR_ENTITY_ID: ", ".join(result["missing"])},
            )
        return result

    async def restore(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        result: dict[str, Any] = await manager.async_restore(
            call.data[ATTR_SLOT],
            _targets(hass, call),
            context=call.context,
            only_if_unchanged=call.data.get(ATTR_ONLY_IF_UNCHANGED, manager.settings.only_if_unchanged),
            transition=call.data.get(ATTR_TRANSITION),
            forget=call.data.get(ATTR_FORGET, manager.settings.forget),
        )
        return result

    async def forget(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        slot = call.data.get(ATTR_SLOT)
        entity_ids = _targets(hass, call)
        if slot is None and entity_ids is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="forget_nothing")
        result: dict[str, Any] = manager.async_forget(slot, entity_ids, context=call.context)
        return result

    async def create_scene(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        slot = call.data[ATTR_SLOT]
        if not hass.services.has_service(SCENE_DOMAIN, SCENE_SERVICE_CREATE):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="scene_unavailable")
        states, skipped = await manager.async_scene_states(slot, _targets(hass, call))
        if not states:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="scene_empty", translation_placeholders={ATTR_SLOT: slot}
            )
        # Own namespace: every scene from Recall is scene.recall_<id>, so it never collides with Hue & Co.
        scene_id = call.data.get(ATTR_SCENE_ID) or slugify(slot)
        if not scene_id.startswith(SCENE_PREFIX):
            scene_id = f"{SCENE_PREFIX}{scene_id}"
        scene_entity = f"{SCENE_DOMAIN}.{scene_id}"
        before = hass.states.get(scene_entity)
        await hass.services.async_call(
            SCENE_DOMAIN,
            SCENE_SERVICE_CREATE,
            {ATTR_SCENE_ID: scene_id, "entities": states},
            blocking=True,
            context=call.context,
        )
        # scene.create only logs a warning when a scene from scenes.yaml (e.g. a hand-made recall_…) already uses
        # this id and keeps it.
        # A created (or replaced) scene always writes a new state object.
        created = hass.states.get(scene_entity)
        if created is None or created is before:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="scene_exists",
                translation_placeholders={ATTR_ENTITY_ID: scene_entity},
            )
        return {ATTR_SLOT: slot, "scene": scene_entity, ATTR_ENTITY_ID: sorted(states), "skipped": skipped}

    for name, handler, schema in (
        (SERVICE_SAVE, save, SAVE_SCHEMA),
        (SERVICE_RESTORE, restore, RESTORE_SCHEMA),
        (SERVICE_FORGET, forget, FORGET_SCHEMA),
        (SERVICE_CREATE_SCENE, create_scene, CREATE_SCENE_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL)
