"""Bedingung `recall.is_saved`: Ist für die Ziel-Entitäten in einem Slot etwas gemerkt (und unverändert)?"""

from __future__ import annotations

from typing import Any, Unpack, override

from homeassistant.const import CONF_OPTIONS, CONF_TARGET
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import Condition, ConditionCheckParams, ConditionConfig
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import ATTR_SLOT, DEFAULT_SLOT, DOMAIN, REASON_HANDED_OVER
from .manager import resolve_targets

ATTR_UNCHANGED = "unchanged"

IS_SAVED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Required(CONF_OPTIONS, default={}): {
            vol.Optional(ATTR_SLOT, default=DEFAULT_SLOT): vol.All(cv.string, vol.Length(min=1, max=64)),
            vol.Optional(ATTR_UNCHANGED, default=False): cv.boolean,
        },
    }
)


class IsSavedCondition(Condition):
    """Wahr, wenn alle Ziel-Entitäten im Slot gemerkt sind – mit `unchanged` zusätzlich ohne Handeingriff.

    Ziele werden wie bei den Aktionen aufgelöst (alte `group.*`-Gruppen zu ihren Mitgliedern).
    """

    @classmethod
    @override
    async def async_validate_config(cls, hass: HomeAssistant, config: ConfigType) -> ConfigType:
        validated: ConfigType = IS_SAVED_SCHEMA(config)
        return validated

    def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
        super().__init__(hass, config)
        assert config.target is not None
        options: dict[str, Any] = config.options or {}
        self._target: dict[str, Any] = dict(config.target)
        self._slot: str = options.get(ATTR_SLOT, DEFAULT_SLOT)
        self._unchanged: bool = options.get(ATTR_UNCHANGED, False)

    @override
    def _async_check(self, **kwargs: Unpack[ConditionCheckParams]) -> bool:
        entries = self._hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            return False
        manager = entries[0].runtime_data
        entity_ids = resolve_targets(self._hass, self._target)
        if not entity_ids:
            return False
        for entity_id in entity_ids:
            snap = manager.get(self._slot, entity_id)
            if snap is None:
                return False
            # Von einem anderen Recall-Slot verstellt (Übergabe) zählt nicht als Handeingriff.
            reason = manager.manual_reason(snap) if self._unchanged else None
            if reason is not None and reason[0] != REASON_HANDED_OVER:
                return False
        return True


CONDITIONS: dict[str, type[Condition]] = {"is_saved": IsSavedCondition}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:
    """Bedingungen von Recall."""
    return CONDITIONS
