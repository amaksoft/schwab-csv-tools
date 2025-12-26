#!/usr/bin/env python3
"""Fix missing symbols in Schwab transaction CSV files.

This script processes Schwab transaction CSVs and fills in missing symbols
by either looking them up in a mapping file or generating synthetic symbols
from descriptions.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Import shared utilities from common module
from .common import (
    DESC_LONG,
    DESC_MEDIUM,
    DESC_SHORT,
    MAX_COLUMNS,
    MAX_ROUNDING_DIFF,
    MIN_COLUMNS,
    MIN_ROUNDING_DIFF,
    REQUIRED_HEADERS,
    SECURITY_ACTIONS,
    ValidationError,
    generate_symbol_from_description,
    parse_currency,
    parse_schwab_date,
    truncate_text,
)


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
                    f"Invalid mapping file at line {line_num}: "
                    f"expected 2 columns, got {len(row)}"
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
                f"  ⚠ Warning: {len(duplicates)} duplicate description(s) "
                f"in mapping file"
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
                f"Expected {MIN_COLUMNS}-{MAX_COLUMNS} columns, "
                f"got {len(headers)}: {filepath}"
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


# ============================================================================
# Symbol Processing Classes
# ============================================================================


class SymbolTracker:
    """Encapsulates symbol assignment logic for missing symbols."""

    def __init__(self, mapping: dict[str, str]):
        """Initialize the symbol tracker.

        Args:
            mapping: Description → symbol mapping dict (case-insensitive)
        """
        self.mapping = mapping
        self.description_to_symbol: dict[str, str] = {}
        self.symbol_counter: dict[str, int] = defaultdict(int)
        self.assignments: list[dict[str, str | int]] = []
        self.missing_symbols = 0
        self.symbols_mapped = 0
        self.symbols_generated = 0
        self.missing_descriptions: dict[str, int] = defaultdict(int)
        self.symbol_assignment_counts: dict[str, dict[str, str | int]] = defaultdict(
            lambda: {"symbol": "", "count": 0}
        )

    def process_missing_symbol(
        self,
        row: dict[str, str],
        row_num: int,
        verbose: bool = False,
    ) -> None:
        """Process a row with missing symbol.

        Args:
            row: CSV row dict
            row_num: Row number (1-indexed, accounting for header)
            verbose: Print detailed output
        """
        action = row.get("Action", "").strip()
        description = row.get("Description", "").strip()

        # Only track missing symbols for security transactions
        is_security_transaction = action in SECURITY_ACTIONS
        if is_security_transaction:
            self.missing_symbols += 1
            desc_key = description if description else "(no description)"
            self.missing_descriptions[desc_key] += 1

        # Only generate symbols for security transactions
        if not is_security_transaction:
            return

        # Generate or lookup symbol
        if not description:
            # No description, use fallback
            generated_symbol = f"UNKNOWN{row_num}"
            source = "FALLBACK"
            if verbose:
                print(
                    f"  ⚠ Warning: Row {row_num} has no description, "
                    f"using {generated_symbol}"
                )
        else:
            generated_symbol, source = self._generate_or_lookup_symbol(
                description, verbose
            )

        # Update row
        row["Symbol"] = generated_symbol

        # Track assignment
        self.symbol_assignment_counts[description]["symbol"] = generated_symbol
        count = self.symbol_assignment_counts[description]["count"]
        assert isinstance(count, int)
        self.symbol_assignment_counts[description]["count"] = count + 1

        # Track change for logging
        self.assignments.append(
            {
                "row": row_num,
                "description": description,
                "symbol": generated_symbol,
                "source": source,
            }
        )

        if verbose:
            desc_short = truncate_text(description, DESC_SHORT)
            print(f"  Row {row_num}: {desc_short} → {generated_symbol} [{source}]")

    def _generate_or_lookup_symbol(
        self, description: str, verbose: bool = False
    ) -> tuple[str, str]:
        """Get symbol from mapping or generate new.

        Args:
            description: Security description
            verbose: Print warnings for collisions

        Returns:
            Tuple of (symbol, source) where source is MAPPED, REUSED, or GENERATED
        """
        description_lower = description.lower()

        # Check if we've already assigned a symbol for this description
        if description_lower in self.description_to_symbol:
            # Reuse the same symbol for identical descriptions
            self.symbols_generated += 1
            return self.description_to_symbol[description_lower], "REUSED"

        # Try mapping first
        if description_lower in self.mapping:
            symbol = self.mapping[description_lower]
            self.symbols_mapped += 1
            # Remember this mapping
            self.description_to_symbol[description_lower] = symbol
            return symbol, "MAPPED"

        # Generate synthetic symbol
        symbol = generate_symbol_from_description(description)

        # Handle collisions (only for different descriptions)
        self.symbol_counter[symbol] += 1
        if self.symbol_counter[symbol] > 1:
            # Append numeric suffix
            collision_num = self.symbol_counter[symbol] - 1
            symbol = f"{symbol}{collision_num}"
            if verbose:
                print(f"  ⚠ Warning: Symbol collision, using {symbol}")

        self.symbols_generated += 1
        # Remember this description→symbol mapping
        self.description_to_symbol[description_lower] = symbol
        return symbol, "GENERATED"

    def write_log(
        self, output_dir: Path, input_stem: str, verbose: bool = False
    ) -> None:
        """Write symbol assignment log file.

        Args:
            output_dir: Directory for log file
            input_stem: Input filename stem
            verbose: Print log file path
        """
        if not self.assignments:
            return

        log_file = output_dir / f"{input_stem}_symbol_changes.log"
        with log_file.open("w", newline="", encoding="utf-8") as f:
            log_writer = csv.DictWriter(
                f,
                fieldnames=["Row", "Original Description", "Assigned Symbol", "Source"],
            )
            log_writer.writeheader()
            for change in self.assignments:
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


class RoundingFixer:
    """Encapsulates rounding error detection and fixing logic."""

    def __init__(self) -> None:
        """Initialize the rounding fixer."""
        self.fixes: list[dict[str, str | int]] = []

    def process_rows(self, rows: list[dict[str, str]], verbose: bool = False) -> None:
        """Fix rounding errors in all rows.

        Args:
            rows: List of CSV row dicts (modified in-place)
            verbose: Print detailed output
        """
        for row_num, row in enumerate(rows, start=2):
            self._check_and_fix_row(row, row_num, verbose)

    def _check_and_fix_row(
        self, row: dict[str, str], row_num: int, verbose: bool = False
    ) -> None:
        """Check single row for rounding error and fix if found.

        Args:
            row: CSV row dict (modified in-place)
            row_num: Row number
            verbose: Print detailed output
        """
        price_str = row.get("Price", "").strip()
        quantity_str = row.get("Quantity", "").strip()
        amount_str = row.get("Amount", "").strip()
        fees_str = row.get("Fees & Comm", "").strip()

        # Skip if any required field is missing
        if not price_str or not quantity_str or not amount_str:
            return

        try:
            # Parse values
            price = parse_currency(price_str)
            quantity = float(quantity_str.replace(",", ""))
            amount = parse_currency(amount_str)
            fees = parse_currency(fees_str) if fees_str else 0.0

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
            # Only fix small discrepancies
            # (MIN_ROUNDING_DIFF < diff < MAX_ROUNDING_DIFF)
            diff = abs(calculated_amount - amount)

            if MIN_ROUNDING_DIFF < diff < MAX_ROUNDING_DIFF:
                # Fix the amount
                sign = "-" if amount < 0 else ""
                fixed_amount = f"{sign}${abs(calculated_amount):.2f}"

                old_amount = row["Amount"]
                row["Amount"] = fixed_amount

                # Track fix
                self.fixes.append(
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
                        f"  Row {row_num}: {symbol} amount {old_amount} → "
                        f"{fixed_amount} (diff: ${diff:.3f})"
                    )

        except (ValueError, ZeroDivisionError):
            # Skip rows with invalid numeric data
            pass

    def write_log(
        self, output_dir: Path, input_stem: str, verbose: bool = False
    ) -> None:
        """Write rounding fixes log file.

        Args:
            output_dir: Directory for log file
            input_stem: Input filename stem
            verbose: Print log file path
        """
        if not self.fixes:
            return

        log_file = output_dir / f"{input_stem}_rounding_fixes.log"
        with log_file.open("w", newline="", encoding="utf-8") as f:
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
            for fix in self.fixes:
                log_writer.writerow(
                    {
                        "Row": fix["row"],
                        "Symbol": fix["symbol"],
                        "Description": fix["description"],
                        "Old Amount": fix["old_amount"],
                        "New Amount": fix["new_amount"],
                        "Difference": fix["diff"],
                    }
                )
        if verbose:
            print(f"  Rounding fixes log written to: {log_file}")

    @property
    def fixes_count(self) -> int:
        """Get number of fixes applied.

        Returns:
            Number of rounding fixes
        """
        return len(self.fixes)

    def get_affected_symbols(self) -> dict[str, int]:
        """Get symbols that had rounding fixes with their counts.

        Returns:
            Dict mapping symbol to number of rounding fixes for that symbol
        """
        symbol_counts: dict[str, int] = defaultdict(int)
        for fix in self.fixes:
            symbol = fix["symbol"]
            if symbol:
                symbol_counts[str(symbol)] += 1
        return dict(symbol_counts)


# ============================================================================
# CSV Processing Functions
# ============================================================================


def _load_csv_rows(input_file: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Load CSV rows into memory.

    Args:
        input_file: Input CSV file path

    Returns:
        Tuple of (headers, rows)

    Raises:
        ValidationError: If no headers found
    """
    with input_file.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames

    if not headers:
        raise ValidationError(f"No headers found in file: {input_file}")

    return list(headers), rows


def _filter_by_tax_year(
    rows: list[dict[str, str]], tax_year_end: datetime, verbose: bool = False
) -> tuple[list[dict[str, str]], int]:
    """Filter rows after tax year end.

    Args:
        rows: List of CSV row dicts
        tax_year_end: UK tax year end date
        verbose: Print detailed output

    Returns:
        Tuple of (filtered_rows, filtered_count)
    """
    filtered_rows = []
    filtered_count = 0

    for row in rows:
        date_str = row.get("Date", "").strip()
        transaction_date = parse_schwab_date(date_str)

        # Keep row if date is on or before tax year end
        # Also keep rows with unparseable dates (warnings will be shown if verbose)
        if transaction_date is None:
            if verbose and date_str:
                print(f"  ⚠ Warning: Could not parse date '{date_str}', keeping row")
            filtered_rows.append(row)
        elif transaction_date <= tax_year_end:
            filtered_rows.append(row)
        else:
            filtered_count += 1
            if verbose:
                desc = truncate_text(row.get("Description", ""), DESC_SHORT)
                print(f"  Filtered: {date_str} - {desc}...")

    if verbose and filtered_count > 0:
        end_date = tax_year_end.strftime("%m/%d/%Y")
        print(f"  Filtered out {filtered_count} row(s) after {end_date}")

    return filtered_rows, filtered_count


def _write_csv_rows(
    output_file: Path, headers: list[str], rows: list[dict[str, str]]
) -> None:
    """Write processed rows to CSV.

    Args:
        output_file: Output CSV file path
        headers: Column headers
        rows: List of CSV row dicts
    """
    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def process_csv(
    input_file: Path,
    output_file: Path,
    mapping: dict[str, str],
    verbose: bool = False,
    write_log: bool = False,
    fix_rounding: bool = False,
    tax_year_end: datetime | None = None,
) -> dict[str, Any]:
    """Process CSV and fix missing symbols and rounding errors.

    Args:
        input_file: Input CSV file path
        output_file: Output CSV file path
        mapping: Description → symbol mapping dict
        verbose: Enable verbose output
        write_log: Write change log file
        fix_rounding: Fix small rounding errors
            (MIN_ROUNDING_DIFF < diff < MAX_ROUNDING_DIFF)
            where quantity * price ≠ amount
        tax_year_end: Optional UK tax year end date; filter out
            transactions after this date

    Returns:
        Dictionary with statistics

    Raises:
        ValidationError: If processing fails
    """
    # Step 1: Load CSV rows
    headers, rows = _load_csv_rows(input_file)

    total_rows = len(rows)

    # Step 2: Filter by tax year if specified
    filtered_count = 0
    if tax_year_end:
        rows, filtered_count = _filter_by_tax_year(rows, tax_year_end, verbose)

    # Step 3: Fix missing symbols
    symbol_tracker = SymbolTracker(mapping)
    for row_num, row in enumerate(rows, start=2):  # start=2 to account for header
        if not row.get("Symbol", "").strip():
            symbol_tracker.process_missing_symbol(row, row_num, verbose)

    # Step 4: Fix rounding errors if requested
    rounding_fixer = RoundingFixer()
    if fix_rounding:
        rounding_fixer.process_rows(rows, verbose)

    # Step 5: Write output CSV
    _write_csv_rows(output_file, headers, rows)

    # Step 6: Write logs if requested
    if write_log:
        symbol_tracker.write_log(input_file.parent, input_file.stem, verbose)
        rounding_fixer.write_log(input_file.parent, input_file.stem, verbose)

    # Return statistics
    return {
        "total_rows": total_rows,
        "filtered_rows": filtered_count,
        "missing_symbols": symbol_tracker.missing_symbols,
        "mapped": symbol_tracker.symbols_mapped,
        "generated": symbol_tracker.symbols_generated,
        "rounding_fixed": rounding_fixer.fixes_count,
        "rounding_affected_symbols": rounding_fixer.get_affected_symbols(),
        "missing_descriptions": symbol_tracker.missing_descriptions,
        "symbol_assignments": symbol_tracker.symbol_assignment_counts,
    }


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
        help=(
            f"fix small rounding errors "
            f"(${MIN_ROUNDING_DIFF:.2f}-${MAX_ROUNDING_DIFF:.2f}) "
            f"where quantity * price ≠ amount"
        ),
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
            print(f"Tax year {args.tax_year}: filtering transactions after {end_date}")

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
                desc_display = truncate_text(desc, DESC_LONG)
                print(f"  • {desc_display} ({count:,} row(s))")

    if stats["mapped"] > 0 or stats["generated"] > 0:
        print()
        print("Symbol assignments:")

        # Show detailed assignments with descriptions and counts
        if stats["symbol_assignments"]:
            for desc, info in stats["symbol_assignments"].items():
                desc_display = truncate_text(desc, DESC_MEDIUM)
                symbol = info["symbol"]
                count = info["count"]
                print(f"  • {desc_display} → {symbol} ({count:,} row(s))")

        # Summary counts
        print()
        if stats["mapped"] > 0:
            print(f"  Total mapped: {stats['mapped']:,} symbol(s) from mapping file")
        if stats["generated"] > 0:
            print(
                f"  Total generated: {stats['generated']:,} symbol(s) from descriptions"
            )

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

    # Show symbols affected by rounding fixes if any
    if stats["rounding_fixed"] > 0 and stats["rounding_affected_symbols"]:
        print()
        print("Rounding errors fixed for:")
        for symbol, count in sorted(stats["rounding_affected_symbols"].items()):
            print(f"  • {symbol} ({count:,} row(s))")

    print(f"  Output: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
