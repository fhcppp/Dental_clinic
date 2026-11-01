"""Domain errors safe to display without revealing stored record details."""


class ClinicError(Exception):
    """Base application error."""


class ValidationError(ClinicError, ValueError):
    """Invalid input to a domain operation."""


class NotFoundError(ClinicError):
    """Requested record does not exist."""


class ConflictError(ClinicError):
    """Operation violates scheduling or lifecycle constraints."""
