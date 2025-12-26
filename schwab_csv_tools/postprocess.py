#!/usr/bin/env python3
"""Fix missing symbols in Schwab transaction CSV files.

This script processes Schwab transaction CSVs and fills in missing symbols
by either looking them up in a mapping file or generating synthetic symbols
from descriptions.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Final

# Constants
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


class ValidationError(Exception):
    """CSV validation error."""

    pass


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
        datetime(2025, 5, 30)
        >>> parse_schwab_date("06/02/2025 as of 05/30/2025")
        datetime(2025, 5, 30)
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


def get_uk_tax_year_end(tax_year: int) -> datetime:
    """Calculate UK tax year end date.

    UK tax year runs from April 6 to April 5 of the following year.
    Tax year YYYY ends on April 5, YYYY+1.

    Args:
        tax_year: Tax year (e.g., 2024 for 2024/2025 tax year)

    Returns:
        End date of tax year (April 5, tax_year+1)

    Examples:
        >>> get_uk_tax_year_end(2024)
        datetime(2025, 4, 5)
    """
    return datetime(tax_year + 1, 4, 5)


def generate_symbol_from_description(description: str) -> str:
    """Generate synthetic ticker symbol from description.

    Algorithm:
    1. Uppercase and normalize
    2. Strip special chars: &, ., -, (), [], commas
    3. Split into words
    4. Take first letter of each word
    5. Truncate to 8 characters max

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
    """
    if not description or not description.strip():
        return "UNKNOWN"

    # Normalize: uppercase and clean
    normalized = description.upper().strip()

    # Remove special characters, keep alphanumeric and spaces
    # Keep numbers if they form words (e.g., "500" in "S&P 500")
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


def load_mapping_file(filepath: Path, verbose: bool = False) -> dict[str, str]:
    """Load description→symbol mappings from CSV file.

    File format:
        Description,Symbol
        ISHARES EDGE MSCI WORLD...,IEMWVF
        VANGUARD FTSE ALL WORLD,VWRL

    Args:
        filepath: Path to mapping CSV file
        verbose: Enable verbose output

    Returns:
        Dict mapping lowercase descriptions to symbols

    Raises:
        ValidationError: If mapping file is invalid
    """
    if not filepath.exists():
        raise ValidationError(f"Mapping file not found: {filepath}")

    mappings = {}
    duplicates = []

    with filepath.open(encoding="utf-8") as f:
        reader = csv.reader(f)

        try:
            headers = next(reader)
        except StopIteration:
            raise ValidationError(f"Empty mapping file: {filepath}")

        # Validate headers (case-insensitive)
        headers_lower = [h.lower().strip() for h in headers]
        if "description" not in headers_lower or "symbol" not in headers_lower:
            raise ValidationError(
                f"Mapping file must have 'Description' and 'Symbol' columns: {filepath}"
            )

        desc_index = headers_lower.index("description")
        symbol_index = headers_lower.index("symbol")

        for line_num, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue  # Skip empty lines

            if len(row) < 2:
                raise ValidationError(
                    f"Invalid mapping file at line {line_num}: expected 2 columns, got {len(row)}"
                )

            description = row[desc_index].strip()
            symbol = row[symbol_index].strip()

            if not description:
                continue  # Skip rows with empty description

            if not symbol:
                raise ValidationError(
                    f"Empty symbol at line {line_num} for description: {description}"
                )

            # Case-insensitive matching
            description_lower = description.lower()

            if description_lower in mappings:
                duplicates.append((line_num, description))

            # Last entry wins
            mappings[description_lower] = symbol

    if verbose:
        print(f"  Loaded {len(mappings)} mapping(s)")
        if duplicates:
            print(
                f"  ⚠ Warning: {len(duplicates)} duplicate description(s) in mapping file"
            )
            for line_num, desc in duplicates[:3]:  # Show first 3
                print(f"    Line {line_num}: {desc[:50]}...")

    return mappings


def validate_schwab_csv(filepath: Path, verbose: bool = False) -> list[str]:
    """Validate Schwab CSV format and return headers.

    Args:
        filepath: Path to transaction CSV
        verbose: Enable verbose output

    Returns:
        List of header strings

    Raises:
        ValidationError: If validation fails
    """
    if not filepath.exists():
        raise ValidationError(f"File not found: {filepath}")

    if not filepath.is_file():
        raise ValidationError(f"Not a file: {filepath}")

    with filepath.open(encoding="utf-8") as f:
        reader = csv.reader(f)

        try:
            headers = next(reader)
        except StopIteration:
            raise ValidationError(f"Empty file: {filepath}")

        # Validate column count
        if len(headers) < MIN_COLUMNS or len(headers) > MAX_COLUMNS:
            raise ValidationError(
                f"Expected {MIN_COLUMNS}-{MAX_COLUMNS} columns, got {len(headers)}: {filepath}"
            )

        # Validate required headers
        headers_set = set(headers)
        missing = REQUIRED_HEADERS - headers_set
        if missing:
            raise ValidationError(f"Missing required headers {missing}: {filepath}")

    if verbose:
        print(f"  Headers: {', '.join(headers[:4])}...")
        print(f"  Column count: {len(headers)}")

    return headers


def process_csv(
    input_file: Path,
    output_file: Path,
    mapping: dict[str, str],
    verbose: bool = False,
    write_log: bool = False,
    fix_rounding: bool = False,
    tax_year_end: datetime | None = None,
) -> dict[str, int]:
    """Process CSV and fix missing symbols and rounding errors.

    Args:
        input_file: Input CSV file path
        output_file: Output CSV file path
        mapping: Description → symbol mapping dict
        verbose: Enable verbose output
        write_log: Write change log file
        fix_rounding: Fix small rounding errors ($0.01 < diff < $1.00)
            where quantity × price ≠ amount
        tax_year_end: Optional UK tax year end date; filter out
            transactions after this date

    Returns:
        Dictionary with statistics

    Raises:
        ValidationError: If processing fails
    """
    # Actions that involve securities and require symbols
    SECURITY_ACTIONS = {
        "Buy",
        "Sell",
        "Stock Plan Activity",
        "Reinvest Shares",
        "Qual Div Reinvest",
        "Cancel Buy",
        "Journal",  # May involve security transfers
    }

    stats = {
        "total_rows": 0,
        "missing_symbols": 0,
        "mapped": 0,
        "generated": 0,
        "rounding_fixed": 0,
        "filtered_rows": 0,
        "missing_descriptions": defaultdict(int),  # Track description counts for missing symbols
        "symbol_assignments": defaultdict(lambda: {"symbol": "", "count": 0}),  # Track symbol->description assignments
    }

    changes = []  # Track all changes for logging
    symbol_tracker: dict[str, int] = defaultdict(
        int
    )  # Track generated symbols for collision detection
    description_to_symbol: dict[
        str, str
    ] = {}  # Track description→symbol mapping to ensure consistency

    # Read input
    with input_file.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames

    if not headers:
        raise ValidationError(f"No headers found in file: {input_file}")

    stats["total_rows"] = len(rows)

    # Filter rows by date if tax_year_end is specified
    if tax_year_end:
        filtered_rows = []
        for row in rows:
            date_str = row.get("Date", "").strip()
            transaction_date = parse_schwab_date(date_str)

            # Keep row if date is on or before tax year end
            # Also keep rows with unparseable dates (warnings will be shown if verbose)
            if transaction_date is None:
                if verbose and date_str:
                    print(
                        f"  ⚠ Warning: Could not parse date '{date_str}', keeping row"
                    )
                filtered_rows.append(row)
            elif transaction_date <= tax_year_end:
                filtered_rows.append(row)
            else:
                stats["filtered_rows"] += 1
                if verbose:
                    desc = row.get("Description", "")[:50]
                    print(f"  Filtered: {date_str} - {desc}...")

        rows = filtered_rows
        if verbose and stats["filtered_rows"] > 0:
            end_date = tax_year_end.strftime("%m/%d/%Y")
            print(
                f"  Filtered out {stats['filtered_rows']} row(s) "
                f"after {end_date}"
            )

    # Process rows
    for row_num, row in enumerate(rows, start=2):  # start=2 to account for header
        # Check if symbol is missing
        symbol = row.get("Symbol", "").strip()
        action = row.get("Action", "").strip()

        if not symbol:
            description = row.get("Description", "").strip()

            # Only track missing symbols for security transactions
            is_security_transaction = action in SECURITY_ACTIONS
            if is_security_transaction:
                stats["missing_symbols"] += 1
                desc_key = description if description else "(no description)"
                stats["missing_descriptions"][desc_key] += 1

            # Only generate symbols for security transactions
            if not is_security_transaction:
                # Non-security transaction, leave symbol empty
                continue

            if not description:
                # No description, can't generate symbol
                generated_symbol = f"UNKNOWN{row_num}"
                if verbose:
                    print(
                        f"  ⚠ Warning: Row {row_num} has no description, using {generated_symbol}"
                    )
            else:
                # Check if we've already assigned a symbol for this description
                description_lower = description.lower()
                if description_lower in description_to_symbol:
                    # Reuse the same symbol for identical descriptions
                    generated_symbol = description_to_symbol[description_lower]
                    stats["generated"] += 1
                    source = "REUSED"
                elif description_lower in mapping:
                    # Try mapping first
                    generated_symbol = mapping[description_lower]
                    stats["mapped"] += 1
                    source = "MAPPED"
                    # Remember this mapping
                    description_to_symbol[description_lower] = generated_symbol
                else:
                    # Generate synthetic symbol
                    generated_symbol = generate_symbol_from_description(description)

                    # Handle collisions (only for different descriptions)
                    symbol_tracker[generated_symbol] += 1
                    if symbol_tracker[generated_symbol] > 1:
                        # Append numeric suffix
                        collision_num = symbol_tracker[generated_symbol] - 1
                        generated_symbol = f"{generated_symbol}{collision_num}"
                        if verbose:
                            print(
                                f"  ⚠ Warning: Symbol collision, using {generated_symbol}"
                            )

                    stats["generated"] += 1
                    source = "GENERATED"
                    # Remember this description→symbol mapping
                    description_to_symbol[description_lower] = generated_symbol

                # Track symbol assignment
                stats["symbol_assignments"][description]["symbol"] = generated_symbol
                stats["symbol_assignments"][description]["count"] += 1

                # Update row
                row["Symbol"] = generated_symbol

                # Track change
                changes.append(
                    {
                        "row": row_num,
                        "description": description,
                        "symbol": generated_symbol,
                        "source": source,
                    }
                )

                if verbose:
                    desc_short = (
                        description[:50] + "..."
                        if len(description) > 50
                        else description
                    )
                    print(
                        f"  Row {row_num}: {desc_short} → {generated_symbol} [{source}]"
                    )

    # Fix rounding errors if requested
    if fix_rounding:
        rounding_changes = []

        for row_num, row in enumerate(rows, start=2):
            price_str = row.get("Price", "").strip()
            quantity_str = row.get("Quantity", "").strip()
            amount_str = row.get("Amount", "").strip()
            fees_str = row.get("Fees & Comm", "").strip()

            # Skip if any required field is missing
            if not price_str or not quantity_str or not amount_str:
                continue

            try:
                # Parse values, removing $ and , characters
                price = float(price_str.replace("$", "").replace(",", ""))
                quantity = float(quantity_str.replace(",", ""))
                amount = float(amount_str.replace("$", "").replace(",", ""))
                fees = (
                    float(fees_str.replace("$", "").replace(",", ""))
                    if fees_str
                    else 0.0
                )

                # Calculate expected amount (accounting for fees)
                # For sells (positive amount): quantity × price - fees
                # For buys (negative amount): -(quantity × price + fees)
                gross_amount = quantity * price
                if amount >= 0:
                    # Sell transaction
                    calculated_amount = gross_amount - fees
                else:
                    # Buy transaction
                    calculated_amount = -(gross_amount + fees)

                # Check if there's a rounding discrepancy
                # Only fix small discrepancies (0.01 < diff < 1.00)
                # Larger differences are likely legitimate (bonds, special pricing, etc.)
                diff = abs(calculated_amount - amount)

                if 0.01 < diff < 1.00:
                    # Fix the amount
                    # Preserve the sign (negative for buys, positive for sells)
                    sign = "-" if amount < 0 else ""
                    fixed_amount = f"{sign}${abs(calculated_amount):.2f}"

                    old_amount = row["Amount"]
                    row["Amount"] = fixed_amount

                    stats["rounding_fixed"] += 1

                    rounding_changes.append(
                        {
                            "row": row_num,
                            "symbol": row.get("Symbol", ""),
                            "description": row.get("Description", "")[:30],
                            "old_amount": old_amount,
                            "new_amount": fixed_amount,
                            "diff": f"${diff:.3f}",
                        }
                    )

                    if verbose:
                        symbol = row.get("Symbol", "N/A")
                        print(
                            f"  Row {row_num}: {symbol} amount {old_amount} → {fixed_amount} (diff: ${diff:.3f})"
                        )

            except (ValueError, ZeroDivisionError):
                # Skip rows with invalid numeric data
                continue

        # Add rounding changes to main changes log if write_log is enabled
        if write_log and rounding_changes:
            rounding_log_file = (
                input_file.parent / f"{input_file.stem}_rounding_fixes.log"
            )
            with rounding_log_file.open("w", newline="", encoding="utf-8") as f:
                log_writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "Row",
                        "Symbol",
                        "Description",
                        "Old Amount",
                        "New Amount",
                        "Difference",
                    ],
                )
                log_writer.writeheader()
                for change in rounding_changes:
                    log_writer.writerow(
                        {
                            "Row": change["row"],
                            "Symbol": change["symbol"],
                            "Description": change["description"],
                            "Old Amount": change["old_amount"],
                            "New Amount": change["new_amount"],
                            "Difference": change["diff"],
                        }
                    )
            if verbose:
                print(f"  Rounding fixes log written to: {rounding_log_file}")

    # Write output
    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    # Write change log if requested
    if write_log and changes:
        log_file = input_file.parent / f"{input_file.stem}_symbol_changes.log"
        with log_file.open("w", newline="", encoding="utf-8") as f:
            log_writer = csv.DictWriter(
                f,
                fieldnames=["Row", "Original Description", "Assigned Symbol", "Source"],
            )
            log_writer.writeheader()
            for change in changes:
                log_writer.writerow(
                    {
                        "Row": change["row"],
                        "Original Description": change["description"],
                        "Assigned Symbol": change["symbol"],
                        "Source": change["source"],
                    }
                )
        if verbose:
            print(f"  Change log written to: {log_file}")

    return stats


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="Fix missing symbols in Schwab transaction CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process with auto-generated symbols
  %(prog)s transactions.csv

  # Use mapping file for known securities
  %(prog)s transactions.csv -m mappings.csv

  # Fix rounding errors in amounts
  %(prog)s transactions.csv --fix-rounding

  # Filter transactions for UK tax year 2024 (ends April 5, 2025)
  %(prog)s transactions.csv --tax-year 2024

  # Specify output path with all fixes
  %(prog)s transactions.csv -o fixed_transactions.csv --fix-rounding

  # Use both mapping and rounding fixes with verbose output
  %(prog)s transactions.csv -m mappings.csv --fix-rounding -v

  # Complete workflow for UK tax year 2024
  %(prog)s transactions.csv -m mappings.csv --fix-rounding --tax-year 2024 -v
""",
    )

    parser.add_argument(
        "input_file",
        type=Path,
        help="Schwab transaction CSV file to process",
    )

    parser.add_argument(
        "-m",
        "--mapping",
        type=Path,
        metavar="FILE",
        help="CSV file mapping descriptions to symbols (Description,Symbol)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="output filename (default: INPUT_processed.csv)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose output with detailed logging",
    )

    parser.add_argument(
        "--write-log",
        action="store_true",
        help="write symbol changes to LOG file (INPUT_symbol_changes.log)",
    )

    parser.add_argument(
        "--fix-rounding",
        action="store_true",
        help="fix small rounding errors ($0.01-$1.00) where quantity × price ≠ amount",
    )

    parser.add_argument(
        "--tax-year",
        type=int,
        metavar="YEAR",
        help="UK tax year (filters out transactions after April 5, YEAR+1)",
    )

    return parser


def main() -> int:
    """Main execution flow."""
    parser = create_parser()
    args = parser.parse_args()

    verbose = args.verbose
    input_file = args.input_file

    # Determine output path
    if args.output is None:
        output_path = input_file.parent / f"{input_file.stem}_processed.csv"
    else:
        output_path = args.output

    print(f"Processing {input_file}...")

    # Validate input file
    if verbose:
        print()
        print("Validating input CSV...")

    try:
        validate_schwab_csv(input_file, verbose)
    except ValidationError as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        return 1

    # Load mapping file if provided
    mapping = {}
    if args.mapping:
        if verbose:
            print()
            print(f"Loading mapping file: {args.mapping}...")

        try:
            mapping = load_mapping_file(args.mapping, verbose)
        except ValidationError as e:
            print(f"✗ Error: {e}", file=sys.stderr)
            return 1

    # Calculate tax year end if provided
    tax_year_end = None
    if args.tax_year:
        tax_year_end = get_uk_tax_year_end(args.tax_year)
        if verbose:
            end_date = tax_year_end.strftime("%m/%d/%Y")
            print()
            print(
                f"Tax year {args.tax_year}: filtering transactions "
                f"after {end_date}"
            )

    # Process CSV
    if verbose:
        print()
        print("Processing transactions...")

    try:
        stats = process_csv(
            input_file,
            output_path,
            mapping,
            verbose,
            args.write_log,
            args.fix_rounding,
            tax_year_end,
        )
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        return 1

    # Print summary
    print()
    if stats["missing_symbols"] == 0:
        print("No missing symbols found - all transactions have symbols!")
    else:
        print(f"Found {stats['missing_symbols']:,} row(s) with missing symbols")

        # Show all missing symbol descriptions with counts
        if stats["missing_descriptions"]:
            print()
            print("Missing symbols for:")
            for desc, count in stats["missing_descriptions"].items():
                desc_display = desc[:80] + "..." if len(desc) > 80 else desc
                print(f"  • {desc_display} ({count:,} row(s))")

    if stats["mapped"] > 0 or stats["generated"] > 0:
        print()
        print("Symbol assignments:")

        # Show detailed assignments with descriptions and counts
        if stats["symbol_assignments"]:
            for desc, info in stats["symbol_assignments"].items():
                desc_display = desc[:60] + "..." if len(desc) > 60 else desc
                symbol = info["symbol"]
                count = info["count"]
                print(f"  • {desc_display} → {symbol} ({count:,} row(s))")

        # Summary counts
        print()
        if stats["mapped"] > 0:
            print(f"  Total mapped: {stats['mapped']:,} symbol(s) from mapping file")
        if stats["generated"] > 0:
            print(f"  Total generated: {stats['generated']:,} symbol(s) from descriptions")

    print()
    print("Statistics:")
    print(f"  Total rows: {stats['total_rows']:,}")
    if stats["filtered_rows"] > 0:
        print(f"  Filtered rows (after tax year end): {stats['filtered_rows']:,}")
        print(f"  Remaining rows: {stats['total_rows'] - stats['filtered_rows']:,}")
    print(f"  Missing symbols: {stats['missing_symbols']:,}")
    print(f"  Symbols mapped: {stats['mapped']:,}")
    print(f"  Symbols generated: {stats['generated']:,}")
    print(f"  Rounding errors fixed: {stats['rounding_fixed']:,}")
    print(f"  Output: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
