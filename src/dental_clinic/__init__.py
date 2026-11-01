"""Local-first dental clinic backend foundation (not for clinical production)."""

from .db import ClinicDatabase
from .errors import ConflictError, NotFoundError, ValidationError
from .services import AppointmentService, OdontogramService, PatientService

__all__ = [
    "ClinicDatabase",
    "PatientService",
    "AppointmentService",
    "OdontogramService",
    "ConflictError",
    "NotFoundError",
    "ValidationError",
]
