"""Herzstück: Zustände merken, Handbetrieb erkennen, wiederherstellen, speichern.

Handbetrieb-Erkennung in einem Satz: Nach dem Merken beobachtet Recall, welchen Zustand die Automation
anfährt (erster ruhiger Zustand = „erwarteter Zustand“); weicht das Gerät später davon ab, hat jemand
eingegriffen und das Wiederherstellen wird übersprungen.

Ablauf je gemerkter Entität (`Snapshot`):

1. **Beruhigen** (`settled = False`): Jede Änderung startet das Ruhefenster (Optionen, Standard 15 s) neu,
   Fahrt-Zwischenstände (opening/closing) zählen nie als fertig. Ändert sich gar nichts, gilt nach
   der Wartezeit (Standard 60 s) der aktuelle Zustand. Greift in dieser Phase ein *fremder Befehl* ein
   (Bedienung in HA mit Benutzer oder eine andere Automation), endet sie sofort mit dem letzten ruhigen Zustand.
2. **Erwartet** (`settled = True`): Änderungen im Kontext der merkenden Automation (gleicher Lauf, z. B. nach
   einer Verzögerung) starten Schritt 1 neu. Jede andere Änderung wird mit dem erwarteten Zustand verglichen
   (`compare.deviation`, Toleranz in Prozentpunkten); die erste Abweichung merkt sich Zeit und Quelle.
3. **Wiederherstellen**: Entspricht das Gerät noch dem erwarteten Zustand (oder ist es noch in Schritt 1),
   stellt Recall den gemerkten Zustand über HAs Szenen-Mechanik (`async_reproduce_state`) her.
4. **Übergabe**: Weicht das Gerät nur ab, weil ein *anderer* Slot danach genau unseren erwarteten Zustand gemerkt
   (und dann verstellt) hat, ist das kein Handeingriff: Unser gemerkter Zustand geht an diesen Slot über
   (dessen `saved` wird unser `saved`), ohne Bewegung, unser Slot wird vergessen. Stellt der andere Slot später
   wieder her, landet das Gerät beim ursprünglichen Zustand. Greift jemand nach dessen Merken ein, erkennt der
   andere Slot das selbst als Handeingriff.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.json import json_bytes
from homeassistant.helpers.state import async_reproduce_state
from homeassistant.helpers.storage import Store, UnsupportedStorageVersionError
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.loader import IntegrationNotFound, async_get_integration
from homeassistant.util import dt as dt_util
from homeassistant.util.json import json_loads

from .compare import describe, deviation, is_known, is_transitional, restorable_attributes, saved_attributes
from .const import (
    ATTR_SLOT,
    DEFAULT_TOLERANCE,
    DOMAIN,
    EVENT_FORGOTTEN,
    EVENT_RESTORED,
    EVENT_SAVED,
    EVENT_SKIPPED,
    REASON_HANDED_OVER,
    REASON_MANUAL,
    REASON_MOVING,
    REASON_NOT_SAVED,
    REASON_UNAVAILABLE,
    REASON_UNSUPPORTED,
    SOURCE_AUTOMATION,
    SOURCE_DEVICE,
    SOURCE_RECALL,
    SOURCE_UNKNOWN,
    SOURCE_USER,
    STORAGE_KEY,
    STORAGE_MINOR_VERSION,
    STORAGE_VERSION,
)
from .settings import Settings

_LOGGER = logging.getLogger(__name__)

MAX_CONTEXTS = 5
SAVE_DELAY = 2

type RecallConfigEntry = ConfigEntry[RecallManager]
type StateDict = dict[str, Any]


def state_to_dict(state: State) -> StateDict:
    """Zustand + die Attribute, die Vergleich und Wiederherstellung brauchen, JSON-fest (Speicher und Vergleich)."""
    kept = saved_attributes(state.domain, state.attributes)
    attributes = json_loads(json_bytes(kept)) if kept else {}
    return {"state": state.state, "attributes": attributes if isinstance(attributes, dict) else {}}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def resolve_targets(hass: HomeAssistant, selection: Mapping[str, Any]) -> set[str]:
    """Entitäten aus einem Ziel (Entität, Gerät, Bereich, Etage, Label) – Aktionen und Bedingung lösen gleich auf
    (alte `group.*`-Gruppen werden zu ihren Mitgliedern)."""
    selected = async_extract_referenced_entity_ids(hass, TargetSelection(dict(selection)))
    return selected.referenced | selected.indirectly_referenced


def context_source(context: Context) -> str:
    """Wer hat geändert: Bedienung in HA, Automation/Skript oder das Gerät selbst (Taster, App, Fernbedienung)."""
    if context.user_id:
        return SOURCE_USER
    if context.parent_id:
        return SOURCE_AUTOMATION
    return SOURCE_DEVICE


@dataclass(slots=True)
class Snapshot:
    """Gemerkter Zustand einer Entität in einem Slot."""

    entity_id: str
    saved: StateDict
    saved_at: datetime
    tolerance: float
    expires_at: datetime | None = None
    contexts: list[str] = field(default_factory=list)
    settled: bool = False
    settle_start: datetime | None = None
    last_change: datetime | None = None
    candidate: StateDict | None = None
    expected: StateDict | None = None
    changed_at: datetime | None = None
    changed_by: str | None = None
    changed_detail: str | None = None
    # Fremder Befehl kam, während die eigene Fahrt noch lief: erwartet ist dann nur der Stand davor.
    interrupted: bool = False

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    def settle_due(self, settings: Settings) -> datetime:
        """Wann das Beruhigen spätestens geprüft wird."""
        start = self.settle_start or self.saved_at
        base = self.last_change + settings.settle_quiet if self.last_change else start + settings.settle_wait
        return min(base, start + settings.settle_max)

    def restart_settling(self, now: datetime, context_id: str | None, current: State | None) -> None:
        """Eigene Änderung (gleicher Automationslauf): erwarteten Zustand neu lernen."""
        if context_id and context_id not in self.contexts:
            self.contexts = [*self.contexts, context_id][-MAX_CONTEXTS:]
        self.settled = False
        self.settle_start = now
        self.last_change = now if current is not None else None
        if current is not None and not is_transitional(self.domain, current.state):
            self.candidate = state_to_dict(current)
        self.interrupted = False
        self.clear_change()

    def settle(self, expected: StateDict) -> None:
        self.settled = True
        self.expected = expected
        self.last_change = None

    def clear_change(self) -> None:
        self.changed_at = None
        self.changed_by = None
        self.changed_detail = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "saved": self.saved,
            "saved_at": _iso(self.saved_at),
            "tolerance": self.tolerance,
            "expires_at": _iso(self.expires_at),
            "contexts": self.contexts,
            "settled": self.settled,
            "settle_start": _iso(self.settle_start),
            "candidate": self.candidate,
            "expected": self.expected,
            "changed_at": _iso(self.changed_at),
            "changed_by": self.changed_by,
            "changed_detail": self.changed_detail,
            "interrupted": self.interrupted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], now: datetime) -> Snapshot:
        """Aus dem Speicher; fehlende Felder (ältere Formate) bekommen sichere Vorgaben.

        Ohne `saved.state` ist der Eintrag unbrauchbar (ValueError → wird beim Laden verworfen).
        Kontexte werden nicht übernommen: Automationsläufe von vor dem Neustart gibt es nicht mehr, ihre
        IDs könnten nie wieder als „eigene“ Änderung auftauchen.
        """
        saved = data["saved"]
        if not isinstance(saved, dict) or "state" not in saved:
            raise ValueError("saved ohne state")
        snap = cls(
            entity_id=data["entity_id"],
            saved=saved,
            saved_at=_dt(data.get("saved_at")) or now,
            tolerance=float(data.get("tolerance", DEFAULT_TOLERANCE)),
            expires_at=_dt(data.get("expires_at")),
            contexts=[],
            settled=bool(data.get("settled")) and data.get("expected") is not None,
            candidate=data.get("candidate"),
            expected=data.get("expected"),
            changed_at=_dt(data.get("changed_at")),
            changed_by=data.get("changed_by"),
            changed_detail=data.get("changed_detail"),
            interrupted=bool(data.get("interrupted")),
        )
        if not snap.settled:
            # Nach einem Neustart: Ruhefenster neu beginnen, der Zustand vor dem Neustart zählt als ruhig.
            snap.settle_start = now
        return snap


class RecallStore(Store[dict[str, Any]]):
    """Speicher mit Versionswechsel: Minor-Stufen bleiben lesbar, eine neuere Major-Version wird nicht geraten."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        # Eine neuere Major-Version (Downgrade) lehnt Store selbst ab (UnsupportedStorageVersionError).
        # Neue Felder kommen nur über Minor-Stufen dazu; Snapshot.from_dict füllt fehlende mit Vorgaben.
        return old_data


class RecallManager:
    """Alle Slots, Beobachtung der Geräte, Zeitplan für Beruhigen und Ablauf."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.slots: dict[str, dict[str, Snapshot]] = {}
        self.settings = Settings.from_options(entry.options)
        self._store = RecallStore(hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_MINOR_VERSION)
        self._listeners: list[CALLBACK_TYPE] = []
        self._tracked: frozenset[str] = frozenset()
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_registry: CALLBACK_TYPE | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._supported: dict[str, bool] = {}
        self._dirty = False
        self._stopped = False

    # ── Lebenszyklus ──────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        try:
            data = await self._store.async_load() or {}
        except UnsupportedStorageVersionError:
            _LOGGER.error("Gemerkte Zustände stammen von einer neueren Recall-Version und werden nicht gelesen")
            data = {}
        now = dt_util.utcnow()
        for slot, snaps in (data.get("slots") or {}).items():
            loaded: dict[str, Snapshot] = {}
            for entity_id, raw in snaps.items():
                try:
                    loaded[entity_id] = Snapshot.from_dict({**raw, "entity_id": entity_id}, now)
                except (KeyError, TypeError, ValueError):
                    _LOGGER.warning(
                        "Gemerkter Zustand für %s (Slot %s) ist beschädigt und wird verworfen", entity_id, slot
                    )
            if loaded:
                self.slots[slot] = loaded

    @callback
    def async_start(self) -> None:
        """Beobachten und Zeitplan starten (abgelaufene Einträge räumt der erste Durchlauf weg)."""
        self._async_refresh_tracking()
        self._unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_on_registry, event_filter=self._registry_filter
        )
        self._async_tick(dt_util.utcnow())

    @callback
    def async_stop(self) -> None:
        """Beobachten und Termine beenden; danach plant nichts mehr ein Speichern."""
        self._stopped = True
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_registry:
            self._unsub_registry()
            self._unsub_registry = None
        self._tracked = frozenset()

    async def async_flush(self) -> None:
        """Verzögertes Speichern sofort erledigen (Entladen): kein alter Termin schreibt später noch."""
        if self._dirty:
            self._dirty = False
            await self._store.async_save(self._data_to_save())

    @callback
    def async_update_settings(self, settings: Settings) -> None:
        """Neue Optionen ohne Neustart: Termine mit den neuen Fenstern neu planen, Sensor auffrischen.

        Die gemerkten Zustände selbst ändern sich dabei nicht, also wird auch nichts geschrieben.
        """
        self.settings = settings
        if self._stopped:
            return  # entladen: keinen neuen Termin mehr anlegen
        self._async_schedule()
        self._async_notify()

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    # ── Abfragen ──────────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return sum(len(snaps) for snaps in self.slots.values())

    def get(self, slot: str, entity_id: str) -> Snapshot | None:
        return self.slots.get(slot, {}).get(entity_id)

    def manual_reason(self, snap: Snapshot, current: State | None = None) -> tuple[str, str] | None:
        """(Grund, Detail), falls seit dem Merken jemand eingegriffen hat – sonst None.

        Grund `handed_over`: Die Abweichung kommt von einem anderen Slot (Detail = dessen Name), kein Handeingriff.
        """
        current = current or self.hass.states.get(snap.entity_id)
        if current is None or not is_known(current.state) or not snap.settled or snap.expected is None:
            return None
        if is_transitional(snap.domain, current.state):
            return REASON_MOVING, current.state
        now = state_to_dict(current)
        detail = deviation(snap.domain, snap.expected, now, snap.tolerance)
        if not detail:
            return None
        if heirs := self.handover_slots(snap, snap.expected):
            return REASON_HANDED_OVER, ", ".join(heirs)
        if snap.interrupted:
            detail = f"interrupted while moving, now {describe(snap.domain, now)}"
        return REASON_MANUAL, detail

    def handover_slots(self, snap: Snapshot, expected: StateDict) -> list[str]:
        """Andere Slots, die nach uns genau unseren erwarteten Zustand gemerkt haben (Übergabe-Erben)."""
        return [
            name
            for name, snaps in sorted(self.slots.items())
            if (other := snaps.get(snap.entity_id)) is not None
            and other is not snap
            and other.saved_at >= snap.saved_at
            and deviation(snap.domain, expected, other.saved, snap.tolerance) is None
        ]

    def changed_by(self, snap: Snapshot) -> str:
        """Wer zuerst abwich; `unknown`, wenn das niemand gesehen hat (z. B. verstellt, während HA aus war)."""
        return snap.changed_by or SOURCE_UNKNOWN

    def summary(self, snap: Snapshot) -> dict[str, str | None]:
        """Kurzfassung für Sensor und Options-Menü."""
        return {"saved": describe(snap.domain, snap.saved), "expected": describe(snap.domain, snap.expected)}

    # ── Aktionen ──────────────────────────────────────────────────────────────

    @callback
    def async_save(
        self,
        slot: str,
        entity_ids: Iterable[str],
        *,
        context: Context,
        expires_after: timedelta | None,
        overwrite: bool,
        tolerance: float,
    ) -> dict[str, Any]:
        now = dt_util.utcnow()
        snaps = self.slots.setdefault(slot, {})
        saved: list[str] = []
        kept: list[str] = []
        missing: list[str] = []
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None or not is_known(state.state):
                missing.append(entity_id)
                continue
            existing = snaps.get(entity_id)
            if existing is not None and not overwrite:
                # Ursprünglichen Zustand behalten, aber Änderungen dieses Laufs gelten als eigene.
                existing.restart_settling(now, context.id, None)
                if expires_after is not None:
                    existing.expires_at = now + expires_after
                kept.append(entity_id)
                continue
            snaps[entity_id] = Snapshot(
                entity_id=entity_id,
                saved=state_to_dict(state),
                saved_at=now,
                tolerance=tolerance,
                expires_at=now + expires_after if expires_after else None,
                contexts=[context.id],
                settle_start=now,
                candidate=state_to_dict(state),
            )
            saved.append(entity_id)
        if not snaps:
            del self.slots[slot]
        if saved or kept:
            self.hass.bus.async_fire(EVENT_SAVED, {ATTR_SLOT: slot, ATTR_ENTITY_ID: saved + kept}, context=context)
            self._async_changed()
        return {ATTR_SLOT: slot, "saved": saved, "kept": kept, "missing": missing}

    async def async_restore(
        self,
        slot: str,
        entity_ids: list[str] | None,
        *,
        context: Context,
        only_if_unchanged: bool,
        transition: float | None,
        forget: bool,
    ) -> dict[str, Any]:
        # Gleichzeitige Aufrufe für denselben Slot nacheinander: keine doppelten Befehle und Ereignisse.
        async with self._locks.setdefault(slot, asyncio.Lock()):
            return await self._async_restore(
                slot,
                entity_ids,
                context=context,
                only_if_unchanged=only_if_unchanged,
                transition=transition,
                forget=forget,
            )

    async def _async_restore(
        self,
        slot: str,
        entity_ids: list[str] | None,
        *,
        context: Context,
        only_if_unchanged: bool,
        transition: float | None,
        forget: bool,
    ) -> dict[str, Any]:
        snaps = self.slots.get(slot, {})
        if entity_ids is None and not snaps:
            item = {ATTR_ENTITY_ID: None, "reason": REASON_NOT_SAVED, "detail": f"slot {slot} is empty"}
            return {ATTR_SLOT: slot, "restored": [], "skipped": [{**item, "changed_by": None}]}
        targets = entity_ids if entity_ids is not None else list(snaps)
        for domain in {e.split(".", 1)[0] for e in targets if e in snaps}:
            await self._async_check_supported(domain)

        to_restore: list[Snapshot] = []
        skipped: list[dict[str, Any]] = []
        drop: list[Snapshot] = []
        handed: list[Snapshot] = []
        for entity_id in targets:
            snap = snaps.get(entity_id)
            if snap is None:
                skipped.append(_skip(entity_id, REASON_NOT_SAVED))
                continue
            current = self.hass.states.get(entity_id)
            if not self._supported.get(snap.domain, False):
                skipped.append(_skip(entity_id, REASON_UNSUPPORTED, snap.domain))
                if forget:
                    drop.append(snap)
                continue
            if current is None or not is_known(current.state):
                # Bleibt gemerkt: ein späterer Versuch kann klappen, wenn das Gerät zurück ist.
                skipped.append(_skip(entity_id, REASON_UNAVAILABLE))
                continue
            manual = self.manual_reason(snap, current) if only_if_unchanged else None
            if manual and manual[0] == REASON_HANDED_OVER:
                assert snap.expected is not None  # sonst gäbe es keine Abweichung
                for heir in self.handover_slots(snap, snap.expected):
                    self.slots[heir][entity_id].saved = dict(snap.saved)
                skipped.append(_skip(entity_id, REASON_HANDED_OVER, manual[1], SOURCE_RECALL))
                handed.append(snap)
                continue
            if manual:
                by = self.changed_by(snap) if manual[0] == REASON_MANUAL else None
                skipped.append(_skip(entity_id, manual[0], manual[1], by))
                if forget:
                    drop.append(snap)
                continue
            to_restore.append(snap)

        now = dt_util.utcnow()
        if not forget:
            # Vorher eintragen: Die Änderungen durchs Wiederherstellen gelten als eigene, der erwartete Zustand
            # wird danach neu gelernt.
            for snap in to_restore:
                snap.restart_settling(now, context.id, None)
        if to_restore:
            options: dict[str, Any] = {} if transition is None else {"transition": transition}
            try:
                await async_reproduce_state(
                    self.hass,
                    [
                        State(
                            s.entity_id,
                            s.saved["state"],
                            restorable_attributes(s.domain, s.saved.get("attributes", {})),
                        )
                        for s in to_restore
                    ],
                    context=context,
                    reproduce_options=options,
                )
            except ServiceValidationError:
                raise  # schon verständlich übersetzt (z. B. vom Gerät selbst)
            except HomeAssistantError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="restore_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

        restored = [s.entity_id for s in to_restore]
        if forget:
            drop.extend(to_restore)
        dropped = self._async_drop(slot, drop)
        handed_ids = self._async_drop(slot, handed)

        if restored:
            self.hass.bus.async_fire(EVENT_RESTORED, {ATTR_SLOT: slot, ATTR_ENTITY_ID: restored}, context=context)
        for item in skipped:
            self.hass.bus.async_fire(EVENT_SKIPPED, {ATTR_SLOT: slot, **item}, context=context)
            if item["reason"] in (REASON_MANUAL, REASON_MOVING, REASON_HANDED_OVER):
                _LOGGER.debug(
                    "%s (Slot %s) nicht wiederhergestellt: %s %s",
                    item[ATTR_ENTITY_ID],
                    slot,
                    item["reason"],
                    item["detail"],
                )
        for gone, reason in ((dropped, "restore"), (handed_ids, REASON_HANDED_OVER)):
            if gone:
                self.hass.bus.async_fire(
                    EVENT_FORGOTTEN, {ATTR_SLOT: slot, ATTR_ENTITY_ID: gone, "reason": reason}, context=context
                )
        if restored or dropped or handed_ids:
            self._async_changed()
        return {ATTR_SLOT: slot, "restored": restored, "skipped": skipped}

    @callback
    def _async_drop(self, slot: str, snaps: list[Snapshot]) -> list[str]:
        """Genau diese Snapshots entfernen – nicht einen, den ein paralleles `save` inzwischen ersetzt hat."""
        current = self.slots.get(slot)
        gone: list[str] = []
        if current is None:
            return gone
        for snap in snaps:
            if current.get(snap.entity_id) is snap:
                del current[snap.entity_id]
                gone.append(snap.entity_id)
        if not current:
            del self.slots[slot]
        return gone

    async def _async_check_supported(self, domain: str) -> None:
        """Kann HA diese Domäne wiederherstellen (reproduce_state)? Einmal je Domäne nachsehen."""
        if domain in self._supported:
            return
        try:
            integration = await async_get_integration(self.hass, domain)
        except IntegrationNotFound:
            self._supported[domain] = False
            return
        self._supported[domain] = bool(integration.platforms_exists(["reproduce_state"]))

    @callback
    def async_forget(
        self, slot: str | None, entity_ids: list[str] | None, *, context: Context | None = None, reason: str = "action"
    ) -> dict[str, Any]:
        forgotten: dict[str, list[str]] = {}
        if slot is not None and slot not in self.slots:
            return {"forgotten": forgotten, "skipped": [{ATTR_SLOT: slot, "reason": REASON_NOT_SAVED}]}
        for name in [slot] if slot is not None else list(self.slots):
            snaps = self.slots[name]
            gone = [e for e in (entity_ids if entity_ids is not None else list(snaps)) if e in snaps]
            for entity_id in gone:
                del snaps[entity_id]
            if not snaps:
                del self.slots[name]
            if gone:
                forgotten[name] = gone
                self.hass.bus.async_fire(
                    EVENT_FORGOTTEN, {ATTR_SLOT: name, ATTR_ENTITY_ID: gone, "reason": reason}, context=context
                )
        if forgotten:
            self._async_changed()
        return {"forgotten": forgotten}

    # ── Beobachten ────────────────────────────────────────────────────────────

    @callback
    def _async_on_state(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None or not is_known(new.state):
            return
        entity_id = event.data["entity_id"]
        now = dt_util.utcnow()
        ctx = new.context
        changed = False
        reschedule = False
        for snaps in self.slots.values():
            snap = snaps.get(entity_id)
            if snap is None:
                continue
            before = snap.as_dict()
            last_change = snap.last_change
            own = ctx.id in snap.contexts or (ctx.parent_id is not None and ctx.parent_id in snap.contexts)
            moving = is_transitional(snap.domain, new.state)
            if not snap.settled:
                if not own and (ctx.user_id or ctx.parent_id):
                    # Fremder Befehl, bevor die Automation fertig war: erwartet ist der letzte ruhige Zustand.
                    old = event.data["old_state"]
                    snap.interrupted = old is not None and is_transitional(snap.domain, old.state)
                    snap.settle(snap.candidate or snap.saved)
                    self._async_check_change(snap, new, now)
                    changed = True
                    continue
                snap.last_change = now
                if not moving:
                    snap.candidate = state_to_dict(new)
            elif own:
                snap.restart_settling(now, None, new)
            elif not moving:
                self._async_check_change(snap, new, now)
            # Nur speichern und den Sensor schreiben, wenn sich etwas Gespeichertes geändert hat; ein neues
            # Ruhefenster (last_change) braucht nur einen neuen Termin.
            if snap.as_dict() != before:
                changed = True
            elif snap.last_change != last_change:
                reschedule = True
        if changed:
            self._async_changed()
        elif reschedule:
            self._async_schedule()

    @callback
    def _async_check_change(self, snap: Snapshot, new: State, now: datetime) -> None:
        reason = self.manual_reason(snap, new)
        if reason is None:
            snap.clear_change()
            return
        if snap.changed_at is None:
            snap.changed_at = now
            snap.changed_by = self._source(snap, new.context)
        # Detail immer zum letzten Stand (nach einer Fahrt: wo es stehen blieb, nicht der Zwischenstand)
        snap.changed_detail = reason[1]

    def _source(self, snap: Snapshot, ctx: Context) -> str:
        """Wer hat geändert – `recall`, wenn es der Lauf einer Automation mit eigenem Slot für dieselbe Entität war."""
        for snaps in self.slots.values():
            other = snaps.get(snap.entity_id)
            if (
                other is not None
                and other is not snap
                and (ctx.id in other.contexts or ctx.parent_id in other.contexts)
            ):
                return SOURCE_RECALL
        return context_source(ctx)

    @callback
    def _registry_filter(self, event_data: er.EventEntityRegistryUpdatedData) -> bool:
        return event_data["action"] == "remove" and event_data["entity_id"] in self._tracked

    @callback
    def _async_on_registry(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """Entität gelöscht: überall vergessen (sie kommt so nicht wieder)."""
        self.async_forget(None, [event.data["entity_id"]], reason="entity_removed")

    @callback
    def _async_tick(self, now: datetime) -> None:
        """Beruhigen abschließen, Abgelaufenes vergessen, nächsten Termin planen."""
        self._unsub_timer = None
        now = dt_util.utcnow()
        changed = False
        expired: dict[str, list[str]] = {}
        for slot, snaps in self.slots.items():
            for snap in snaps.values():
                if snap.expires_at and snap.expires_at <= now:
                    expired.setdefault(slot, []).append(snap.entity_id)
                    continue
                if snap.settled or snap.settle_due(self.settings) > now:
                    continue
                current = self.hass.states.get(snap.entity_id)
                start = snap.settle_start or snap.saved_at
                if current is not None and is_known(current.state) and not is_transitional(snap.domain, current.state):
                    snap.settle(state_to_dict(current))
                elif now >= start + self.settings.settle_max:
                    snap.settle(snap.candidate or snap.saved)
                else:
                    snap.last_change = now  # noch in Fahrt oder nicht erreichbar: weiter warten
                changed = True
        for slot, entity_ids in expired.items():
            self.async_forget(slot, entity_ids, reason="expired")
        if changed and not expired:
            self._async_changed()
        elif not changed and not expired:
            self._async_schedule()

    # ── Intern ────────────────────────────────────────────────────────────────

    @callback
    def _async_changed(self) -> None:
        if self._stopped:
            return  # entladen: kein Termin darf die Datei später wieder anlegen
        self._dirty = True
        self._store.async_delay_save(self._data_for_delayed_save, SAVE_DELAY)
        self._async_refresh_tracking()
        self._async_schedule()
        self._async_notify()

    @callback
    def _async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _data_for_delayed_save(self) -> dict[str, Any]:
        """Das verzögerte Speichern schreibt gleich: danach muss das Entladen nicht noch einmal schreiben."""
        self._dirty = False
        return self._data_to_save()

    @callback
    def _async_refresh_tracking(self) -> None:
        wanted = frozenset(e for snaps in self.slots.values() for e in snaps)
        if wanted == self._tracked:
            return
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self._tracked = wanted
        if wanted:
            self._unsub_state = async_track_state_change_event(self.hass, sorted(wanted), self._async_on_state)

    @callback
    def _async_schedule(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        due: list[datetime] = []
        for snaps in self.slots.values():
            for snap in snaps.values():
                if not snap.settled:
                    due.append(snap.settle_due(self.settings))
                if snap.expires_at:
                    due.append(snap.expires_at)
        if due:
            self._unsub_timer = async_track_point_in_utc_time(self.hass, self._async_tick, min(due))

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "slots": {
                slot: {entity_id: snap.as_dict() for entity_id, snap in snaps.items()}
                for slot, snaps in self.slots.items()
            }
        }

    def diagnostics(self) -> dict[str, Any]:
        return self._data_to_save()


def _skip(entity_id: str, reason: str, detail: str | None = None, changed_by: str | None = None) -> dict[str, Any]:
    return {ATTR_ENTITY_ID: entity_id, "reason": reason, "detail": detail, "changed_by": changed_by}


async def async_remove_storage(hass: HomeAssistant) -> None:
    """Speicherdatei löschen (Eintrag entfernt), ohne einen zweiten Manager samt Listenern zu bauen."""
    await Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY).async_remove()
