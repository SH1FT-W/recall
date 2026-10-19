"""Einrichtung mit einem Klick (nur ein Eintrag) und „Konfigurieren“: Standardwerte + gemerkte Zustände."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    DurationSelector,
    DurationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    DEFAULT_FORGET,
    DEFAULT_ONLY_IF_UNCHANGED,
    DEFAULT_SETTLE_MAX,
    DEFAULT_SETTLE_QUIET,
    DEFAULT_SETTLE_WAIT,
    DEFAULT_TOLERANCE,
    DOMAIN,
    NAME,
    OPT_EXPIRES_AFTER,
    OPT_FORGET,
    OPT_ONLY_IF_UNCHANGED,
    OPT_SETTLE_MAX,
    OPT_SETTLE_QUIET,
    OPT_SETTLE_WAIT,
    OPT_TOLERANCE,
    REASON_HANDED_OVER,
    SECTION_DETECTION,
    SECTION_EXPIRY,
    SECTION_RESTORE,
)

CONF_SLOTS = "slots"


def _number(minimum: float, maximum: float, step: float, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX)
    )


def _settings_schema(options: dict[str, Any]) -> vol.Schema:
    restore = options.get(SECTION_RESTORE, {})
    detection = options.get(SECTION_DETECTION, {})
    expiry = options.get(SECTION_EXPIRY, {})
    expires = expiry.get(OPT_EXPIRES_AFTER)
    return vol.Schema(
        {
            vol.Required(SECTION_RESTORE): section(
                vol.Schema(
                    {
                        vol.Required(
                            OPT_ONLY_IF_UNCHANGED,
                            default=restore.get(OPT_ONLY_IF_UNCHANGED, DEFAULT_ONLY_IF_UNCHANGED),
                        ): BooleanSelector(),
                        vol.Required(OPT_FORGET, default=restore.get(OPT_FORGET, DEFAULT_FORGET)): BooleanSelector(),
                    }
                ),
                {"collapsed": False},
            ),
            vol.Required(SECTION_DETECTION): section(
                vol.Schema(
                    {
                        vol.Required(OPT_TOLERANCE, default=detection.get(OPT_TOLERANCE, DEFAULT_TOLERANCE)): _number(
                            0, 50, 1, "%"
                        ),
                        vol.Required(
                            OPT_SETTLE_QUIET, default=detection.get(OPT_SETTLE_QUIET, DEFAULT_SETTLE_QUIET)
                        ): _number(3, 300, 1, "s"),
                        vol.Required(
                            OPT_SETTLE_WAIT, default=detection.get(OPT_SETTLE_WAIT, DEFAULT_SETTLE_WAIT)
                        ): _number(5, 600, 5, "s"),
                        vol.Required(
                            OPT_SETTLE_MAX, default=detection.get(OPT_SETTLE_MAX, DEFAULT_SETTLE_MAX)
                        ): _number(1, 120, 1, "min"),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_EXPIRY): section(
                vol.Schema(
                    {
                        vol.Optional(
                            OPT_EXPIRES_AFTER, description={"suggested_value": expires} if expires else None
                        ): DurationSelector(DurationSelectorConfig(enable_day=True)),
                    }
                ),
                {"collapsed": False},
            ),
        }
    )


class RecallConfigFlow(ConfigFlow, domain=DOMAIN):
    """Kein Formular nötig – Recall braucht keine Zugangsdaten."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RecallOptionsFlow:
        return RecallOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user")


class RecallOptionsFlow(OptionsFlow):
    """Menü: Standardwerte oder gemerkte Zustände ansehen und vergessen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "saved"])

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            expiry = user_input.get(SECTION_EXPIRY) or {}
            if not any((expiry.get(OPT_EXPIRES_AFTER) or {}).values()):
                user_input = {**user_input, SECTION_EXPIRY: {}}  # 0 = aus
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="settings", data_schema=_settings_schema(dict(self.config_entry.options)))

    async def async_step_saved(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        manager = entry.runtime_data
        if user_input is not None:
            for slot in user_input.get(CONF_SLOTS, []):
                manager.async_forget(slot, None)
            return self.async_create_entry(data=dict(entry.options))
        if not manager.slots:
            return self.async_abort(reason="nothing_saved")
        options: list[SelectOptionDict] = []
        lines: list[str] = []
        for slot, snaps in sorted(manager.slots.items()):
            names = []
            for entity_id, snap in snaps.items():
                state = self.hass.states.get(entity_id)
                name = state.name if state else entity_id
                reason = manager.manual_reason(snap)
                mark = ""
                if reason and reason[0] == REASON_HANDED_OVER:
                    mark = f" ↪ {reason[1]}"
                elif reason:
                    mark = " ✋"
                expiry = f" ⏳ {dt_util.as_local(snap.expires_at):%d.%m. %H:%M}" if snap.expires_at else ""
                names.append(f"  - {name}: {manager.summary(snap)['saved']}{expiry}{mark}")
            options.append(SelectOptionDict(value=slot, label=f"{slot} ({len(snaps)})"))
            lines.append(f"- **{slot}**\n" + "\n".join(names))
        return self.async_show_form(
            step_id="saved",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SLOTS, default=[]): SelectSelector(
                        SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            description_placeholders={"overview": "\n".join(lines)},
        )
