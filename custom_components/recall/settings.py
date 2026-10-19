"""Globale Standardwerte aus den Optionen (Einstellungen → Recall → Konfigurieren)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    DEFAULT_FORGET,
    DEFAULT_ONLY_IF_UNCHANGED,
    DEFAULT_SETTLE_MAX,
    DEFAULT_SETTLE_QUIET,
    DEFAULT_SETTLE_WAIT,
    DEFAULT_TOLERANCE,
    OPT_EXPIRES_AFTER,
    OPT_FORGET,
    OPT_ONLY_IF_UNCHANGED,
    OPT_SETTLE_MAX,
    OPT_SETTLE_QUIET,
    OPT_SETTLE_WAIT,
    OPT_TOLERANCE,
    SECTION_DETECTION,
    SECTION_EXPIRY,
    SECTION_RESTORE,
)


def _duration(value: Any) -> timedelta | None:
    """Dauer aus dem Dauer-Wähler; leer oder 0 = aus."""
    if not value:
        return None
    try:
        period: timedelta = cv.time_period(value)
    except vol.Invalid:
        return None
    return period if period > timedelta(0) else None


@dataclass(frozen=True, slots=True)
class Settings:
    """Was gilt, wenn eine Aktion ein Feld nicht setzt."""

    only_if_unchanged: bool = DEFAULT_ONLY_IF_UNCHANGED
    forget: bool = DEFAULT_FORGET
    tolerance: float = DEFAULT_TOLERANCE
    settle_quiet: timedelta = timedelta(seconds=DEFAULT_SETTLE_QUIET)
    settle_wait: timedelta = timedelta(seconds=DEFAULT_SETTLE_WAIT)
    settle_max: timedelta = timedelta(minutes=DEFAULT_SETTLE_MAX)
    expires_after: timedelta | None = None

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> Settings:
        restore = options.get(SECTION_RESTORE) or {}
        detection = options.get(SECTION_DETECTION) or {}
        expiry = options.get(SECTION_EXPIRY) or {}
        return cls(
            only_if_unchanged=bool(restore.get(OPT_ONLY_IF_UNCHANGED, DEFAULT_ONLY_IF_UNCHANGED)),
            forget=bool(restore.get(OPT_FORGET, DEFAULT_FORGET)),
            tolerance=float(detection.get(OPT_TOLERANCE, DEFAULT_TOLERANCE)),
            settle_quiet=timedelta(seconds=float(detection.get(OPT_SETTLE_QUIET, DEFAULT_SETTLE_QUIET))),
            settle_wait=timedelta(seconds=float(detection.get(OPT_SETTLE_WAIT, DEFAULT_SETTLE_WAIT))),
            settle_max=timedelta(minutes=float(detection.get(OPT_SETTLE_MAX, DEFAULT_SETTLE_MAX))),
            expires_after=_duration(expiry.get(OPT_EXPIRES_AFTER)),
        )
