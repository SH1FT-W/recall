"""Aktionen recall.save / recall.restore / recall.forget (in async_setup registriert, mit Antwortdaten)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    ATTR_EXPIRES_AFTER,
    ATTR_FORGET,
    ATTR_ONLY_IF_UNCHANGED,
    ATTR_OVERWRITE,
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

    for name, handler, schema in (
        (SERVICE_SAVE, save, SAVE_SCHEMA),
        (SERVICE_RESTORE, restore, RESTORE_SCHEMA),
        (SERVICE_FORGET, forget, FORGET_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL)
