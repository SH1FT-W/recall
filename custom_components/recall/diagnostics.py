"""Diagnose-Download: Optionen und alle Slots mit gemerktem, erwartetem und aktuellem Zustand (geschwärzt)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import ATTR_ENTITY_PICTURE, ATTR_GPS_ACCURACY, ATTR_LATITUDE, ATTR_LONGITUDE, CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant

from .manager import RecallConfigEntry, state_to_dict

# Sensible Attribute, die in gemerkten/erwarteten/aktuellen Zuständen stecken können (Kamera, Medien, Personen …)
TO_REDACT = {
    CONF_ACCESS_TOKEN,
    ATTR_ENTITY_PICTURE,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_GPS_ACCURACY,
    "entity_picture_local",
    "media_image_url",
    "stream_source",
    "token",
    "api_key",
    "password",
    "ip",
    "ip_address",
    "mac",
    "mac_address",
    "address",
    "user_id",
    "device_trackers",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: RecallConfigEntry) -> dict[str, Any]:
    manager = entry.runtime_data
    data = manager.diagnostics()
    for slot, snaps in manager.slots.items():
        for entity_id, snap in snaps.items():
            current = hass.states.get(entity_id)
            item = data["slots"][slot][entity_id]
            item["current"] = state_to_dict(current) if current else None
            manual = manager.manual_reason(snap, current)
            item["would_skip"] = {"reason": manual[0], "detail": manual[1]} if manual else None
    # Kontext-IDs sind nur intern; Benutzer-IDs speichert Recall gar nicht.
    for snaps in data["slots"].values():
        for item in snaps.values():
            item["contexts"] = len(item["contexts"])
    redacted: dict[str, Any] = async_redact_data(data, TO_REDACT)
    return {"options": dict(entry.options), **redacted}
