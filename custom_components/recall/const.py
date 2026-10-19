"""Konstanten für Recall."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "recall"
NAME: Final = "Recall"

STORAGE_KEY: Final = f"{DOMAIN}.snapshots"
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 2

DEFAULT_SLOT: Final = "default"
DEFAULT_TOLERANCE: Final = 3

# Standardwerte (in den Optionen änderbar, je Aktion überschreibbar)
DEFAULT_ONLY_IF_UNCHANGED: Final = True
DEFAULT_FORGET: Final = True
# Beruhigungsfenster: so lange muss ein Gerät nach dem Merken still stehen, bis sein
# Zustand als „von der Automation angefahren“ (erwarteter Zustand) gilt.
DEFAULT_SETTLE_QUIET: Final = 15  # Sekunden
# Ändert sich nach dem Merken gar nichts, gilt der gemerkte Zustand nach dieser Zeit als erwartet.
DEFAULT_SETTLE_WAIT: Final = 60  # Sekunden
# Spätestens dann wird der erwartete Zustand festgeschrieben (Gerät, das nie zur Ruhe kommt).
DEFAULT_SETTLE_MAX: Final = 10  # Minuten

# Optionen (Options-Flow, gruppiert)
SECTION_RESTORE: Final = "restore"
SECTION_DETECTION: Final = "detection"
SECTION_EXPIRY: Final = "expiry"
OPT_ONLY_IF_UNCHANGED: Final = "only_if_unchanged"
OPT_FORGET: Final = "forget"
OPT_TOLERANCE: Final = "tolerance"
OPT_SETTLE_QUIET: Final = "settle_quiet"
OPT_SETTLE_WAIT: Final = "settle_wait"
OPT_SETTLE_MAX: Final = "settle_max"
OPT_EXPIRES_AFTER: Final = "expires_after"

ATTR_SLOT: Final = "slot"
ATTR_EXPIRES_AFTER: Final = "expires_after"
ATTR_OVERWRITE: Final = "overwrite"
ATTR_TOLERANCE: Final = "tolerance"
ATTR_ONLY_IF_UNCHANGED: Final = "only_if_unchanged"
ATTR_FORGET: Final = "forget"
ATTR_TRANSITION: Final = "transition"

EVENT_SAVED: Final = f"{DOMAIN}_saved"
EVENT_RESTORED: Final = f"{DOMAIN}_restored"
EVENT_SKIPPED: Final = f"{DOMAIN}_skipped"
EVENT_FORGOTTEN: Final = f"{DOMAIN}_forgotten"

# Gründe fürs Überspringen (Antwortdaten, Ereignis, Diagnose)
REASON_NOT_SAVED: Final = "not_saved"
REASON_UNAVAILABLE: Final = "unavailable"
REASON_MANUAL: Final = "manual"
REASON_MOVING: Final = "moving"
# Ein anderer Slot hat den erwarteten Zustand danach gemerkt und verstellt: gemerkter Zustand geht an ihn über.
REASON_HANDED_OVER: Final = "handed_over"
# Domäne kann HA nicht wiederherstellen (kein reproduce_state).
REASON_UNSUPPORTED: Final = "unsupported"

# Wer hat eingegriffen
SOURCE_USER: Final = "user"
SOURCE_AUTOMATION: Final = "automation"
SOURCE_DEVICE: Final = "device"
# Eine Automation mit eigenem Recall-Slot (deren Merk-Lauf)
SOURCE_RECALL: Final = "recall"
# Unbekannt (z. B. verstellt, während HA aus war)
SOURCE_UNKNOWN: Final = "unknown"

SAVER_DOMAIN: Final = "saver"
ISSUE_SAVER_INSTALLED: Final = "saver_installed"
