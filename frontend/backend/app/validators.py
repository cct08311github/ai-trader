"""Input validators for API endpoints."""
import re
from fastapi import HTTPException


def validate_symbol(symbol: str) -> str:
    """Validate Taiwan stock symbol format (4-6 digits)."""
    s = symbol.strip().upper()
    if not re.match(r'^\d{4,6}$', s):
        raise HTTPException(status_code=422, detail=f"Invalid symbol format: {symbol}")
    return s


def validate_quantity(qty: int) -> int:
    """Validate order quantity (positive integer)."""
    if not isinstance(qty, int) or qty <= 0:
        raise HTTPException(status_code=422, detail=f"Invalid quantity: {qty}")
    return qty
