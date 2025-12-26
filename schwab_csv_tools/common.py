#!/usr/bin/env python3
"""Shared utilities and data structures for Schwab CSV processing tools.

This module contains common functions, constants, and dataclasses used across
all Schwab CSV processing scripts: postprocess, merge_transactions, merge_awards,
and cgt_wrapper.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Final

# ============================================================================
# Constants
# ============================================================================

# Schwab CSV structure
REQUIRED_HEADERS: Final[set[str]] = {
    "Date",
    "Action",
    "Symbol",
    "Description",
    "Price",
    "Quantity",
    "Fees & Comm",
    "Amount",
}

MIN_COLUMNS: Final = 8
MAX_COLUMNS: Final = 9
MAX_SYMBOL_LENGTH: Final = 8

# Security actions that require symbols
SECURITY_ACTIONS: Final[set[str]] = {
    "Buy",
    "Sell",
    "Stock Plan Activity",
    "Reinvest Shares",
    "Qual Div Reinvest",
    "Cancel Buy",
    "Journal",  # May involve security transfers
}

# Rounding error thresholds
MIN_ROUNDING_DIFF: Final = 0.01
MAX_ROUNDING_DIFF: Final = 1.00

# Description display lengths (for console output)
DESC_SHORT: Final = 50
DESC_MEDIUM: Final = 60
DESC_LONG: Final = 80


# ============================================================================
# Exceptions
# ============================================================================


class ValidationError(Exception):
    """CSV validation or processing error."""

    pass


# ============================================================================
# Enums
# ============================================================================


class SymbolSource(Enum):
    """Source of symbol assignment."""

    MAPPED = "mapped"  # From mapping file
    GENERATED = "generated"  # Auto-generated from description
    REUSED = "reused"  # Reused from earlier description match
    FALLBACK = "fallback"  # Fallback value (UNKNOWN)


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class Transaction:
    """Represents a single transaction row from Schwab CSV.

    This provides a type-safe wrapper around CSV row dictionaries.
    """

    date: str
    action: str
    symbol: str
    description: str
    quantity: str
    price: str
    fees: str
    amount: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Transaction:
        """Parse transaction from CSV row dictionary.

        Args:
            row: CSV row as dict (from csv.DictReader)

        Returns:
            Transaction instance
        """
        return cls(
            date=row.get("Date", "").strip(),
            action=row.get("Action", "").strip(),
            symbol=row.get("Symbol", "").strip(),
            description=row.get("Description", "").strip(),
            quantity=row.get("Quantity", "").strip(),
            price=row.get("Price", "").strip(),
            fees=row.get("Fees & Comm", "").strip(),
            amount=row.get("Amount", "").strip(),
        )

    def to_dict(self) -> dict[str, str]:
        """Convert back to CSV row format.

        Returns:
            Dict suitable for csv.DictWriter
        """
        return {
            "Date": self.date,
            "Action": self.action,
            "Symbol": self.symbol,
            "Description": self.description,
            "Quantity": self.quantity,
            "Price": self.price,
            "Fees & Comm": self.fees,
            "Amount": self.amount,
        }

    def has_missing_symbol(self) -> bool:
        """Check if symbol is missing or empty.

        Returns:
            True if symbol is missing
        """
        return not self.symbol.strip()

    def is_security_transaction(self) -> bool:
        """Check if this is a security transaction requiring a symbol.

        Returns:
            True if action is in SECURITY_ACTIONS
        """
        return self.action in SECURITY_ACTIONS


@dataclass
class SymbolAssignment:
    """Tracks a symbol assignment or generation event."""

    row_num: int
    description: str
    symbol: str
    source: SymbolSource


@dataclass
class RoundingFix:
    """Tracks a rounding error fix."""

    row_num: int
    symbol: str
    description: str
    old_amount: str
    new_amount: str
    difference: Decimal


@dataclass
class ProcessingStats:
    """Aggregated processing statistics for postprocess operations."""

    total_rows: int = 0
    filtered_rows: int = 0
    missing_symbols: int = 0
    symbols_mapped: int = 0
    symbols_generated: int = 0
    rounding_fixed: int = 0
    missing_descriptions: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    symbol_assignments: dict[str, dict[str, str | int]] = field(
        default_factory=lambda: defaultdict(lambda: {"symbol": "", "count": 0})
    )

    @property
    def rows_processed(self) -> int:
        """Get count of rows actually processed (not filtered).

        Returns:
            Number of rows processed
        """
        return self.total_rows - self.filtered_rows


# ============================================================================
# Date Parsing
# ============================================================================


def parse_schwab_date(date_str: str) -> datetime | None:
    """Parse Schwab date format.

    Handles:
    - Standard format: "MM/DD/YYYY"
    - "as of" format: "06/02/2025 as of 05/30/2025" → uses 05/30/2025

    Args:
        date_str: Date string from Schwab CSV

    Returns:
        Parsed datetime or None if parsing fails

    Examples:
        >>> parse_schwab_date("05/30/2025")
        datetime(2025, 5, 30, 0, 0)
        >>> parse_schwab_date("06/02/2025 as of 05/30/2025")
        datetime(2025, 5, 30, 0, 0)
        >>> parse_schwab_date("")
        None
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Check for "as of" format
    if " as of " in date_str.lower():
        # Extract the actual transaction date (after "as of")
        parts = date_str.lower().split(" as of ")
        if len(parts) == 2:
            date_str = parts[1].strip()

    try:
        return datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        return None


# ============================================================================
# Currency and Number Parsing
# ============================================================================


def parse_currency(currency_str: str) -> float:
    """Parse currency string (removes $ and commas).

    Args:
        currency_str: Currency string like "$1,234.56" or "-$1,234.56"

    Returns:
        Float value

    Raises:
        ValueError: If string cannot be parsed

    Examples:
        >>> parse_currency("$1,234.56")
        1234.56
        >>> parse_currency("-$1,234.56")
        -1234.56
    """
    cleaned = currency_str.replace("$", "").replace(",", "")
    return float(cleaned)


def parse_quantity(qty_str: str) -> float | None:
    """Parse quantity string (handles commas and negatives).

    Args:
        qty_str: Quantity string from CSV

    Returns:
        Float value or None if empty/invalid

    Examples:
        >>> parse_quantity("1,234.5")
        1234.5
        >>> parse_quantity("-100")
        -100.0
        >>> parse_quantity("")
        None
    """
    if not qty_str or qty_str.strip() == "":
        return None

    try:
        return float(qty_str.replace(",", ""))
    except ValueError:
        return None


# ============================================================================
# Text Formatting
# ============================================================================


def truncate_text(text: str, max_length: int = DESC_SHORT) -> str:
    """Truncate text with ellipsis if longer than max_length.

    Args:
        text: Text to truncate
        max_length: Maximum length before truncation (default: DESC_SHORT)

    Returns:
        Truncated text with "..." suffix if needed

    Examples:
        >>> truncate_text("Short text", 50)
        'Short text'
        >>> truncate_text("A" * 100, 50)
        'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...'
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


# ============================================================================
# Account Number Extraction
# ============================================================================


def extract_account_number(filename: str) -> str | None:
    """Extract account number from Schwab CSV filename.

    Looks for patterns like:
    - Individual_XXX157_Transactions_... → "157"
    - SCHWAB1_ONE_INTL_XXX964_Transactions_... → "964"

    Args:
        filename: CSV filename (not full path)

    Returns:
        Account number (last 3-4 digits) or None if not found

    Examples:
        >>> extract_account_number("Individual_XXX157_Transactions_20251114.csv")
        '157'
        >>> extract_account_number("SCHWAB1_XXX964_Transactions.csv")
        '964'
        >>> extract_account_number("transactions.csv")
        None
    """
    # Pattern: XXX followed by 3-4 digits
    match = re.search(r"XXX(\d{3,4})", filename)
    if match:
        return match.group(1)
    return None


def extract_journal_account(desc: str) -> str | None:
    """Extract account number from JOURNAL TO/FRM description.

    Args:
        desc: Journal transaction description

    Returns:
        Account number or None if not found

    Examples:
        >>> extract_journal_account("JOURNAL TO ...964")
        '964'
        >>> extract_journal_account("JOURNAL FRM ...157")
        '157'
        >>> extract_journal_account("Regular transaction")
        None
    """
    # Look for pattern like "...964" or "...157"
    match = re.search(r"\.{3}(\d{3,4})", desc)
    if match:
        return match.group(1)
    return None


# ============================================================================
# Symbol Generation
# ============================================================================


def generate_symbol_from_description(description: str) -> str:
    """Generate synthetic ticker symbol from description.

    Algorithm:
    1. Uppercase and normalize
    2. Strip special chars: &, ., -, (), [], commas, %
    3. Split into words
    4. Take first letter of each word
    5. Truncate to MAX_SYMBOL_LENGTH characters

    Args:
        description: Security description

    Returns:
        Generated symbol (e.g., "ISHARES EDGE MSCI WORLD" → "IEMW")

    Examples:
        >>> generate_symbol_from_description("ISHARES EDGE MSCI WORLD VALUE FACTOR")
        'IEMWVF'
        >>> generate_symbol_from_description("VANGUARD S&P 500 ETF")
        'VSE'
        >>> generate_symbol_from_description("US TREASURY NOTE 4.25%")
        'UTN'
        >>> generate_symbol_from_description("")
        'UNKNOWN'
    """
    if not description or not description.strip():
        return "UNKNOWN"

    # Normalize: uppercase and clean
    normalized = description.upper().strip()

    # Remove special characters, keep alphanumeric and spaces
    cleaned = re.sub(r"[&.,\-\(\)\[\]%]", " ", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned)  # Normalize whitespace

    # Split into words and take first letter of each
    words = cleaned.split()
    if not words:
        return "UNKNOWN"

    # Generate acronym
    acronym = "".join(word[0] for word in words if word)

    # Truncate to max length
    if len(acronym) > MAX_SYMBOL_LENGTH:
        acronym = acronym[:MAX_SYMBOL_LENGTH]

    # If empty after processing, return UNKNOWN
    return acronym if acronym else "UNKNOWN"
