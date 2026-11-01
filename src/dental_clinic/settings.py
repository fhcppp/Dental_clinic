"""Explicit clinic-first-setup settings, independent of OS locale/timezone."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Pinned supported ISO 4217 currency precisions. Reject unknown currencies rather
# than silently assuming two minor units. Extend only with verified ISO metadata.
MINOR_UNITS = {
    "EUR": 2, "USD": 2, "GBP": 2, "CHF": 2, "CAD": 2,
    "AUD": 2, "JPY": 0, "KRW": 0, "CLP": 0, "KWD": 3,
    "BHD": 3, "OMR": 3, "TND": 3, "IRR": 2,
}


@dataclass(frozen=True)
class ClinicSettings:
    timezone: str
    currency: str
    attachment_max_bytes: int = 25 * 1024 * 1024
    backup_daily_count: int = 7
    backup_weekly_count: int = 4
    password_min_length: int = 12
    idle_timeout_minutes: int = 15
    session_lifetime_hours: int = 8
    failed_login_threshold: int = 5

    def __post_init__(self) -> None:
        if not self.timezone or self.timezone.strip() != self.timezone:
            raise ValueError("Clinic timezone must be explicitly chosen")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("Clinic timezone must be a valid IANA zone") from exc
        if self.currency not in MINOR_UNITS:
            raise ValueError("Select a supported currency explicitly")
        if not 1 <= self.attachment_max_bytes <= 1024 * 1024 * 1024:
            raise ValueError("Invalid attachment size limit")
        if not 0 <= self.backup_daily_count <= 365 or not 0 <= self.backup_weekly_count <= 104:
            raise ValueError("Invalid backup retention settings")
        if (self.password_min_length != 12 or self.idle_timeout_minutes != 15
            or self.session_lifetime_hours != 8 or self.failed_login_threshold != 5):
            raise ValueError("Security defaults cannot be weakened by clinic settings")

    @property
    def currency_minor_units(self) -> int:
        return MINOR_UNITS[self.currency]

    def to_minor_units(self, value: Decimal | str) -> int:
        if isinstance(value, float) or not isinstance(value, (Decimal, str)):
            raise ValueError("Amounts must be Decimal or decimal strings")
        try:
            amount = Decimal(value)
            if not amount.is_finite() or amount < 0:
                raise ValueError("Amount must be finite and nonnegative")
            scale = Decimal(10) ** self.currency_minor_units
            result = (amount * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            if result > 2**63 - 1:
                raise ValueError("Amount exceeds SQLite integer range")
            return int(result)
        except Exception as exc:
            raise ValueError("Invalid amount") from exc
