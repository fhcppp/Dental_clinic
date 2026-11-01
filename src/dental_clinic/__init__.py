"""Local-first dental clinic backend foundation (not for clinical production)."""

from .db import ClinicDatabase
from .auth import AuthService
from .attachments import AttachmentVault
from .backup import BackupService
from .clinical import ClinicalService
from .finance import FinanceService
from .medical import MedicalService
from .reporting import ReportingService
from .errors import ConflictError, NotFoundError, ValidationError
from .services import AppointmentService, OdontogramService, PatientService, ClinicRoomService

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
