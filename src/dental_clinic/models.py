"""Immutable backend read models; no UI or networking dependencies."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

AppointmentStatus = Literal["scheduled", "cancelled"]
ToothState = Literal["healthy", "decayed", "missing", "restored", "implant"]


@dataclass(frozen=True, slots=True)
class Patient:
    id: str
    full_name: str
    birth_date: date | None
    phone: str | None
    active: bool
    created_utc: datetime


@dataclass(frozen=True, slots=True)
class Appointment:
    id: str
    patient_id: str
    practitioner_id: str
    start_utc: datetime
    end_utc: datetime
    status: AppointmentStatus


@dataclass(frozen=True, slots=True)
class ToothRecord:
    patient_id: str
    fdi_code: int
    state: ToothState
    updated_utc: datetime
