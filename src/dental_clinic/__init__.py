"""Local-first dental clinic backend foundation (not for clinical production)."""

from .attachments import AttachmentVault
from .auth import AuthService
from .backup import BackupService
from .clinical import ClinicalService
from .db import ClinicDatabase
from .errors import ConflictError, NotFoundError, ValidationError
from .finance import FinanceService
from .medical import MedicalService
from .reporting import ReportingService
from .services import AppointmentService, ClinicRoomService, OdontogramService, PatientService

__all__ = [
    "ClinicDatabase",
    "AuthService",
    "AttachmentVault",
    "BackupService",
    "ClinicalService",
    "FinanceService",
    "MedicalService",
    "ReportingService",
    "ClinicRoomService",
    "PatientService",
    "AppointmentService",
    "OdontogramService",
    "ConflictError",
    "NotFoundError",
    "ValidationError",
]
