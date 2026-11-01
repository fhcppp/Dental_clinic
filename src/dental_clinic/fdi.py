"""FDI/ISO 3950 tooth-code validation for permanent and primary dentition."""

from .errors import ValidationError

PERMANENT_CODES = frozenset(
    quadrant * 10 + tooth
    for quadrant in (1, 2, 3, 4)
    for tooth in range(1, 9)
)
PRIMARY_CODES = frozenset(
    quadrant * 10 + tooth
    for quadrant in (5, 6, 7, 8)
    for tooth in range(1, 6)
)
VALID_FDI_CODES = PERMANENT_CODES | PRIMARY_CODES


def validate_fdi(code: int) -> int:
    """Reject non-standard codes, including bool values (which are ints in Python)."""
    if type(code) is not int or code not in VALID_FDI_CODES:
        raise ValidationError("Invalid FDI tooth code")
    return code
