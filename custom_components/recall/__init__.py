"""Recall – Zustände merken und wiederherstellen, außer jemand hat inzwischen selbst eingegriffen."""

from __future__ import annotations

from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntry, ConfigEntryChange
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, ISSUE_SAVER_INSTALLED, SAVER_DOMAIN
from .manager import RecallConfigEntry, RecallManager, async_remove_storage
from .services import async_register_services
from .settings import Settings

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Aktionen einmal registrieren (auch ohne Eintrag sichtbar, melden dann „nicht eingerichtet“)."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RecallConfigEntry) -> bool:
    manager = RecallManager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    async_check_saver(hass)

    @callback
    def _entry_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if changed.domain == SAVER_DOMAIN:
            async_check_saver(hass)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _entry_changed))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: RecallConfigEntry) -> None:
    """Optionen gespeichert: sofort übernehmen, ohne Neuladen (gemerkte Zustände bleiben unangetastet)."""
    entry.runtime_data.async_update_settings(Settings.from_options(entry.options))


async def async_unload_entry(hass: HomeAssistant, entry: RecallConfigEntry) -> bool:
    """Entladen: erst aufhören zu beobachten, dann Gemerktes sofort schreiben, Hinweis weg.

    Reihenfolge zählt: Eine Zustandsänderung zwischen Schreiben und Stoppen würde sonst noch ein verzögertes
    Speichern einplanen, das nach dem Entladen (oder Löschen) die Datei wieder anlegt.
    """
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False  # pragma: no cover - der Sensor lässt sich immer entladen
    manager = entry.runtime_data
    manager.async_stop()
    await manager.async_flush()
    ir.async_delete_issue(hass, DOMAIN, ISSUE_SAVER_INSTALLED)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: RecallConfigEntry) -> None:
    """Eintrag gelöscht: gemerkte Zustände und Hinweis mit entfernen."""
    await async_remove_storage(hass)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_SAVER_INSTALLED)


@callback
def async_check_saver(hass: HomeAssistant) -> None:
    """Hinweis, solange Saver noch eingerichtet ist (Umstieg nicht vergessen)."""
    if hass.config_entries.async_entries(SAVER_DOMAIN):
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_SAVER_INSTALLED,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_SAVER_INSTALLED,
            learn_more_url="https://github.com/SH1FT-W/recall#migrating-from-saver",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_SAVER_INSTALLED)
