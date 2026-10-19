"""Zustandsvergleich je Domäne (reine Logik)."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.recall.compare import describe, deviation, is_known, is_transitional, restorable_attributes


def s(state: str, **attributes: Any) -> dict[str, Any]:
    return {"state": state, "attributes": attributes}


def test_transitional_and_known() -> None:
    assert is_transitional("cover", "closing")
    assert is_transitional("lock", "unlocking")
    assert not is_transitional("cover", "open")
    assert not is_transitional("light", "closing")
    assert not is_known("unavailable") and not is_known("unknown") and is_known("off")


@pytest.mark.parametrize(
    ("expected", "current", "result"),
    [
        (s("open", current_position=40), s("open", current_position=43), None),
        (s("open", current_position=40), s("open", current_position=44), "current_position: 40 → 44"),
        (
            s("open", current_position=40, current_tilt_position=50),
            s("open", current_position=40, current_tilt_position=0),
            "current_tilt_position: 50 → 0",
        ),
        (s("open"), s("closed"), "state: open → closed"),
        (s("open"), s("open"), None),
        (s("open", current_position=40.5), s("open", current_position=None), None),
    ],
)
def test_cover(expected: dict[str, Any], current: dict[str, Any], result: str | None) -> None:
    assert deviation("cover", expected, current, 3) == result


def test_light() -> None:
    on = s("on", brightness=255, color_mode="color_temp", color_temp_kelvin=2700)
    assert deviation("light", on, s("off"), 3) == "state: on → off"
    assert deviation("light", s("off"), s("off"), 3) is None
    assert deviation("light", on, s("on", brightness=250, color_mode="color_temp", color_temp_kelvin=2800), 3) is None
    assert deviation("light", on, s("on", brightness=200, color_mode="color_temp", color_temp_kelvin=2700), 3) == (
        "brightness: 255 → 200"
    )
    assert deviation("light", on, s("on", brightness=255, color_mode="color_temp", color_temp_kelvin=4000), 3)
    assert deviation("light", on, s("on", brightness=255, color_mode="hs", hs_color=[0, 100]), 3) == (
        "color_mode: color_temp → hs"
    )
    hs = s("on", brightness=255, color_mode="hs", hs_color=[355, 80])
    assert deviation("light", hs, s("on", brightness=255, color_mode="hs", hs_color=[3, 85]), 3) is None
    assert deviation("light", hs, s("on", brightness=255, color_mode="hs", hs_color=[120, 80]), 3)
    assert deviation("light", s("on", effect="rainbow"), s("on", effect="none"), 3) == "effect: rainbow → none"


def test_other_domains() -> None:
    assert deviation("climate", s("heat", temperature=21), s("heat", temperature=21.5), 3) is None
    assert deviation("climate", s("heat", temperature=21), s("heat", temperature=23), 3) == "temperature: 21 → 23"
    assert deviation("climate", s("heat", preset_mode="eco"), s("heat", preset_mode="comfort"), 3)
    assert deviation("fan", s("on", percentage=50), s("on", percentage=52), 3) is None
    assert deviation("fan", s("on", percentage=50), s("on", percentage=80), 3)
    assert deviation("fan", s("on"), s("off"), 3) == "state: on → off"
    assert deviation("fan", s("off", percentage=0), s("off"), 3) is None
    assert deviation("media_player", s("playing", volume_level=0.3), s("paused", volume_level=0.31), 3) is None
    assert deviation("media_player", s("playing", volume_level=0.3), s("off"), 3) == "state: playing → off"
    assert deviation("media_player", s("on", source="TV"), s("on", source="HDMI"), 3) == "source: TV → HDMI"
    assert deviation("humidifier", s("on", humidity=50), s("on", humidity=60), 3)
    assert deviation("water_heater", s("eco", temperature=50), s("eco", temperature=55), 3)
    assert deviation("number", s("5.0"), s("5"), 3) is None
    assert deviation("input_number", s("5"), s("6"), 3) == "state: 5 → 6"
    assert deviation("input_number", s("5"), s("x"), 3) == "state: 5 → x"
    assert deviation("switch", s("on"), s("off"), 3) == "state: on → off"
    assert deviation("valve", s("open", current_position=True), s("open", current_position=False), 3) is None


def test_restorable_attributes() -> None:
    broken = {"color_mode": "color_temp", "color_temp_kelvin": None, "brightness": 80}
    assert restorable_attributes("light", broken) == {"color_temp_kelvin": None, "brightness": 80}
    fine = {"color_mode": "color_temp", "color_temp_kelvin": 2700, "brightness": 80}
    assert restorable_attributes("light", fine) == fine
    assert restorable_attributes("light", {"color_mode": "onoff"}) == {"color_mode": "onoff"}
    assert restorable_attributes("cover", {"color_mode": "hs"}) == {"color_mode": "hs"}


@pytest.mark.parametrize(
    ("domain", "data", "text"),
    [
        (
            "cover",
            {
                "state": "open",
                "attributes": {"current_position": 70, "current_tilt_position": 30},
            },
            "70 % · tilt 30 %",
        ),
        ("cover", {"state": "closed", "attributes": {}}, "closed"),
        ("light", {"state": "off", "attributes": {}}, "off"),
        (
            "light",
            {
                "state": "on",
                "attributes": {"brightness": 255, "hs_color": [30.4, 80], "color_mode": "hs"},
            },
            "on · 100 % · hs 30/80",
        ),
        (
            "light",
            {
                "state": "on",
                "attributes": {"color_mode": "color_temp", "color_temp_kelvin": 2700},
            },
            "on · 2700 K",
        ),
        ("climate", {"state": "heat", "attributes": {"temperature": 21.5}}, "heat · 21.5 °"),
        ("fan", {"state": "on", "attributes": {"percentage": 50}}, "on · 50 %"),
        ("media_player", {"state": "playing", "attributes": {"volume_level": 0.25}}, "playing · vol 25 %"),
        ("switch", {"state": "on"}, "on"),
    ],
)
def test_describe(domain: str, data: dict, text: str) -> None:
    assert describe(domain, data) == text


def test_describe_none() -> None:
    assert describe("cover", None) is None
