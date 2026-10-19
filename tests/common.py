"""Fake-Geräte: Cover und Licht, die auf Aktionen reagieren wie echte (Zustand mit dem Kontext des Befehls)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "recall"

COVER = "cover.jalousie"
LIGHT = "light.spots"


class FakeHome:
    """Registriert cover.*/light.* Aktionen; `calls` sammelt (Aktion, Daten)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False
        self.invalid = False
        self.hook: Any = None  # async, läuft mitten im Jalousie-Befehl (Rennen nachstellen)

    def install(self) -> None:
        for service in ("set_cover_position", "set_cover_tilt_position", "open_cover", "close_cover"):
            self.hass.services.async_register("cover", service, self._cover)
        for service in ("turn_on", "turn_off"):
            self.hass.services.async_register("light", service, self._light)

    def cover(self, position: int, state: str | None = None, *, context: Context | None = None, **attrs: Any) -> None:
        """Gerät meldet eine Position (ohne Kontext = Gerät selbst / Taster)."""
        state = state or ("closed" if position == 0 else "open")
        self.hass.states.async_set(
            COVER, state, {"current_position": position, "supported_features": 15, **attrs}, context=context
        )

    def light(self, on: bool, brightness: int = 255, *, context: Context | None = None, **attrs: Any) -> None:
        attributes = {"brightness": brightness, "color_mode": "brightness", **attrs} if on else {}
        self.hass.states.async_set(LIGHT, "on" if on else "off", attributes, context=context)

    async def _cover(self, call: ServiceCall) -> None:
        from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

        if self.fail:
            raise HomeAssistantError("Jalousie antwortet nicht")
        if self.invalid:
            raise ServiceValidationError("Position ungültig")
        if self.hook is not None:
            await self.hook()
        self.calls.append((f"cover.{call.service}", dict(call.data)))
        position = {"open_cover": 100, "close_cover": 0}.get(call.service, call.data.get("position", 0))
        self.cover(int(position), context=call.context)

    async def _light(self, call: ServiceCall) -> None:
        self.calls.append((f"light.{call.service}", dict(call.data)))
        extra = {k: v for k, v in call.data.items() if k in ("color_temp_kelvin", "hs_color")}
        self.light(call.service == "turn_on", int(call.data.get("brightness", 255)), context=call.context, **extra)


async def call(hass: HomeAssistant, service: str, context: Context | None = None, **data: Any) -> dict[str, Any]:
    response = await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True, context=context or Context()
    )
    assert isinstance(response, dict)
    return response


async def automation(hass: HomeAssistant, position: int, slot: str = "default", **save: Any) -> Context:
    """Wie eine Automation: merken, dann Jalousie fahren – beides im selben Kontext."""
    ctx = Context(parent_id="trigger")
    await call(hass, "save", ctx, entity_id=COVER, slot=slot, **save)
    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": COVER, "position": position}, blocking=True, context=ctx
    )
    return ctx


async def wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
