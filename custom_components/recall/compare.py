"""Reiner Zustandsvergleich ohne HA-Laufzeit: Bewegt sich ein Gerät gerade, weicht es vom erwarteten Zustand ab?"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNKNOWN_STATES = frozenset({"unavailable", "unknown"})

# Zwischenstände während einer Fahrt: zählen nie als Handbetrieb und werden nie als erwartet gemerkt.
TRANSITIONAL: dict[str, frozenset[str]] = {
    "cover": frozenset({"opening", "closing"}),
    "valve": frozenset({"opening", "closing"}),
    "lock": frozenset({"locking", "unlocking", "opening"}),
    "alarm_control_panel": frozenset({"arming", "disarming", "pending"}),
}

# Lichtfarbe: feste Toleranzen, die Prozent-Toleranz gilt für die Helligkeit.
KELVIN_TOLERANCE = 150
HUE_TOLERANCE = 10.0
SATURATION_TOLERANCE = 10.0
TEMPERATURE_TOLERANCE = 0.5


def is_transitional(domain: str, state: str) -> bool:
    """Gerät fährt gerade (Jalousie, Ventil, Schloss)."""
    return state in TRANSITIONAL.get(domain, frozenset())


def is_known(state: str) -> bool:
    """Zustand ist verwertbar (nicht „nicht verfügbar“/„unbekannt“)."""
    return state not in UNKNOWN_STATES


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _differs_num(key: str, expected: Mapping[str, Any], current: Mapping[str, Any], tolerance: float) -> str | None:
    """Zahl weicht um mehr als die Toleranz ab (fehlt der Wert auf einer Seite, wird nicht verglichen)."""
    old, new = _num(expected.get(key)), _num(current.get(key))
    if old is None or new is None:
        return None
    if abs(old - new) > tolerance:
        return f"{key}: {_fmt(old)} → {_fmt(new)}"
    return None


def _differs_eq(key: str, expected: Mapping[str, Any], current: Mapping[str, Any]) -> str | None:
    old, new = expected.get(key), current.get(key)
    if old is None or new is None or old == new:
        return None
    return f"{key}: {old} → {new}"


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _state_change(expected_state: str, current_state: str) -> str | None:
    return None if expected_state == current_state else f"state: {expected_state} → {current_state}"


def _first(*checks: str | None) -> str | None:
    return next((c for c in checks if c), None)


def _cover(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    has_position = "current_position" in ea and "current_position" in ca
    has_tilt = "current_tilt_position" in ea and "current_tilt_position" in ca
    if not has_position and not has_tilt:
        return _state_change(exp, cur)
    return _first(
        _differs_num("current_position", ea, ca, tol),
        _differs_num("current_tilt_position", ea, ca, tol),
    )


def _light(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    if exp != cur:
        return _state_change(exp, cur)
    if cur != "on":
        return None
    brightness = _differs_num("brightness", ea, ca, max(tol, 1) * 255 / 100)
    if brightness:
        return brightness
    mode_old, mode_new = ea.get("color_mode"), ca.get("color_mode")
    if mode_old and mode_new and mode_old != mode_new:
        return f"color_mode: {mode_old} → {mode_new}"
    if mode_new == "color_temp":
        return _differs_num("color_temp_kelvin", ea, ca, KELVIN_TOLERANCE)
    old_hs, new_hs = ea.get("hs_color"), ca.get("hs_color")
    if isinstance(old_hs, (list, tuple)) and isinstance(new_hs, (list, tuple)) and len(old_hs) == len(new_hs) == 2:
        hue = abs(float(old_hs[0]) - float(new_hs[0]))
        hue = min(hue, 360 - hue)
        if hue > HUE_TOLERANCE or abs(float(old_hs[1]) - float(new_hs[1])) > SATURATION_TOLERANCE:
            return f"hs_color: {list(old_hs)} → {list(new_hs)}"
    return _differs_eq("effect", ea, ca)


def _climate(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    return _first(
        _state_change(exp, cur),
        _differs_num("temperature", ea, ca, TEMPERATURE_TOLERANCE),
        _differs_num("target_temp_low", ea, ca, TEMPERATURE_TOLERANCE),
        _differs_num("target_temp_high", ea, ca, TEMPERATURE_TOLERANCE),
        _differs_eq("preset_mode", ea, ca),
        _differs_eq("fan_mode", ea, ca),
    )


def _fan(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    if exp != cur:
        return _state_change(exp, cur)
    if cur != "on":
        return None
    return _first(
        _differs_num("percentage", ea, ca, tol),
        _differs_eq("preset_mode", ea, ca),
        _differs_eq("oscillating", ea, ca),
        _differs_eq("direction", ea, ca),
    )


def _media_player(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    # Wiedergabe-Zustände (playing/paused/idle) wechseln von selbst; nur an/aus zählt.
    if (exp == "off") != (cur == "off"):
        return _state_change(exp, cur)
    return _first(
        _differs_num("volume_level", ea, ca, tol / 100),
        _differs_eq("source", ea, ca),
        _differs_eq("sound_mode", ea, ca),
    )


def _humidifier(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    return _first(_state_change(exp, cur), _differs_num("humidity", ea, ca, tol), _differs_eq("mode", ea, ca))


def _water_heater(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    return _first(
        _state_change(exp, cur),
        _differs_num("temperature", ea, ca, TEMPERATURE_TOLERANCE),
        _differs_eq("operation_mode", ea, ca),
    )


def _numeric(exp: str, cur: str, ea: Mapping[str, Any], ca: Mapping[str, Any], tol: float) -> str | None:
    old, new = _num(exp), _num(cur)
    if old is None or new is None:
        return _state_change(exp, cur)
    return None if abs(old - new) < 1e-9 else _state_change(exp, cur)


_COMPARERS = {
    "cover": _cover,
    "valve": _cover,
    "light": _light,
    "climate": _climate,
    "fan": _fan,
    "media_player": _media_player,
    "humidifier": _humidifier,
    "water_heater": _water_heater,
    "number": _numeric,
    "input_number": _numeric,
}


def deviation(
    domain: str,
    expected: Mapping[str, Any],
    current: Mapping[str, Any],
    tolerance: float,
) -> str | None:
    """Abweichung als lesbare Kurzbeschreibung, None = entspricht dem erwarteten Zustand.

    `expected`/`current` sind `{"state": …, "attributes": {…}}`. Die Toleranz gilt in Prozentpunkten
    (Position, Lamellen, Helligkeit, Lüfterstufe, Lautstärke, Luftfeuchte).
    """
    compare = _COMPARERS.get(domain)
    exp_state, cur_state = str(expected["state"]), str(current["state"])
    if compare is None:
        return _state_change(exp_state, cur_state)
    return compare(exp_state, cur_state, expected.get("attributes", {}), current.get("attributes", {}), tolerance)


# Welche Attribute je Domäne gemerkt werden: genau das, was `deviation`/`describe` vergleichen und HAs
# reproduce_state zum Wiederherstellen liest (gegen HA 2026.9 geprüft). Alles andere (Listen von Optionen,
# Friendly Name, Icons, Medienpositionen, Cover-URLs …) bläht nur den Speicher auf und ändert sich ständig.
# Bewusst nicht dabei: media_content_id/_type (Wiederherstellen würde die Wiedergabe neu starten),
# input_select.options (HA würde die Optionsliste zurücksetzen).
SAVED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "light": frozenset(
        {
            "brightness",
            "color_mode",
            "color_temp_kelvin",
            "hs_color",
            "rgb_color",
            "rgbw_color",
            "rgbww_color",
            "xy_color",
            "effect",
            "white",
        }
    ),
    "cover": frozenset({"current_position", "current_tilt_position"}),
    "valve": frozenset({"current_position"}),
    "climate": frozenset(
        {
            "temperature",
            "target_temp_low",
            "target_temp_high",
            "preset_mode",
            "fan_mode",
            "hvac_mode",
            "swing_mode",
            "swing_horizontal_mode",
            "humidity",
        }
    ),
    "media_player": frozenset({"volume_level", "is_volume_muted", "source", "sound_mode"}),
    "fan": frozenset({"percentage", "preset_mode", "direction", "oscillating"}),
    "humidifier": frozenset({"humidity", "mode"}),
    "water_heater": frozenset({"temperature", "operation_mode", "away_mode"}),
    "vacuum": frozenset({"fan_speed"}),
}


def saved_attributes(domain: str, attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Nur die Attribute behalten, die Vergleich und Wiederherstellung brauchen (Rest: keine)."""
    keep = SAVED_ATTRIBUTES.get(domain)
    if not keep:
        return {}
    return {key: value for key, value in attributes.items() if key in keep}


# Farbmodus → Attribut, das HAs Licht-Wiederherstellung dafür verlangt (fehlt es, stellt sie gar nichts her).
COLOR_MODE_ATTRIBUTE = {
    "color_temp": "color_temp_kelvin",
    "hs": "hs_color",
    "rgb": "rgb_color",
    "rgbw": "rgbw_color",
    "rgbww": "rgbww_color",
    "white": "brightness",
    "xy": "xy_color",
}


def restorable_attributes(domain: str, attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Gemerkte Attribute fürs Wiederherstellen bereinigt.

    Licht: Ein Farbmodus ohne das passende Attribut (z. B. `color_temp` mit `color_temp_kelvin: null`) ließe
    HA das ganze Licht überspringen – ohne den Modus kommen wenigstens An/Aus und Helligkeit zurück.
    """
    cleaned = dict(attributes)
    if domain == "light":
        needed = COLOR_MODE_ATTRIBUTE.get(str(cleaned.get("color_mode")))
        if needed and cleaned.get(needed) is None:
            cleaned.pop("color_mode", None)
    return cleaned


def describe(domain: str, data: Mapping[str, Any] | None) -> str | None:
    """Kurz und lesbar, was ein Zustand bedeutet (z. B. „70 % · tilt 30 %“, „on · 80 % · 2700 K“)."""
    if data is None:
        return None
    state = str(data.get("state"))
    attrs: Mapping[str, Any] = data.get("attributes") or {}
    parts: list[str] = []
    if domain in ("cover", "valve"):
        if (position := _num(attrs.get("current_position"))) is not None:
            parts.append(f"{_fmt(position)} %")
        if (tilt := _num(attrs.get("current_tilt_position"))) is not None:
            parts.append(f"tilt {_fmt(tilt)} %")
        return " · ".join(parts) or state
    parts.append(state)
    if state == "off":
        return state
    if domain == "light":
        if (brightness := _num(attrs.get("brightness"))) is not None:
            parts.append(f"{round(brightness * 100 / 255)} %")
        if (kelvin := _num(attrs.get("color_temp_kelvin"))) is not None and attrs.get("color_mode") == "color_temp":
            parts.append(f"{_fmt(kelvin)} K")
        elif isinstance(hs := attrs.get("hs_color"), (list, tuple)) and len(hs) == 2:
            parts.append(f"hs {round(float(hs[0]))}/{round(float(hs[1]))}")
    elif domain in ("climate", "water_heater"):
        if (temperature := _num(attrs.get("temperature"))) is not None:
            parts.append(f"{_fmt(temperature)} °")
    elif domain == "fan":
        if (percentage := _num(attrs.get("percentage"))) is not None:
            parts.append(f"{_fmt(percentage)} %")
    elif domain == "media_player":
        if (volume := _num(attrs.get("volume_level"))) is not None:
            parts.append(f"vol {round(volume * 100)} %")
    return " · ".join(parts)
