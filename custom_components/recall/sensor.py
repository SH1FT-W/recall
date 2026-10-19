"""Sensor „Gemerkte Zustände“: Anzahl + alles Gemerkte als Attribute (für Bedingungen, Vorlagen, Dashboards)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NAME, REASON_HANDED_OVER
from .manager import RecallConfigEntry, RecallManager, Snapshot

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: RecallConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([SavedStatesSensor(entry.runtime_data)])


def _local(snap_time: Any) -> str | None:
    """Ortszeit, 24 h, sekundengenau – lesbar und weiter mit `as_datetime` auswertbar."""
    return dt_util.as_local(snap_time).isoformat(sep=" ", timespec="seconds") if snap_time else None


class SavedStatesSensor(SensorEntity):
    """Anzahl gemerkter Entitäten über alle Slots."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "saved_states"
    # Attribute können groß werden und ändern sich oft – nicht in die Datenbank.
    _unrecorded_attributes = frozenset({"slots"})

    def __init__(self, manager: RecallManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_saved_states"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=NAME,
            manufacturer="SH1FT-W",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return self._manager.count

    def _describe(self, snap: Snapshot) -> dict[str, Any]:
        reason = self._manager.manual_reason(snap)
        manual = reason is not None and reason[0] != REASON_HANDED_OVER
        summary = self._manager.summary(snap)
        return {
            "saved_state": snap.saved["state"],
            "saved": summary["saved"],
            "saved_at": _local(snap.saved_at),
            "expires_at": _local(snap.expires_at),
            "settled": snap.settled,
            "expected_state": snap.expected["state"] if snap.expected else None,
            "expected": summary["expected"],
            "changed_manually": manual,
            "changed_by": self._manager.changed_by(snap) if reason else None,
            "changed_at": _local(snap.changed_at) if reason else None,
            "handed_over_to": reason[1] if reason and not manual else None,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "slots": {
                slot: {entity_id: self._describe(snap) for entity_id, snap in snaps.items()}
                for slot, snaps in sorted(self._manager.slots.items())
            }
        }
