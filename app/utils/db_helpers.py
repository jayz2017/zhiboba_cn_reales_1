from decimal import Decimal


def to_int(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def to_decimal(value, default=Decimal("0")):
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default
