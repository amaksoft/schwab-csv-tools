#!/usr/bin/env python3
"""Merge multiple Schwab equity awards CSV files.

This script merges multiple Schwab equity awards CSV files into a single file.
Awards files use a special 2-row format where each award spans 2 consecutive rows.

The script handles:
- Validation of file format (15 columns, even line count)
- Merging of 2-row pairs into single records
- Deduplication of identical awards
- Sorting by date (oldest first)
- Splitting back to 2-row format for output
"""

from __future__ import annotations

import argparse
import csv
import datetime
import sys
from pathlib import Path
from typing import Final

# Constants
EXPECTED_COLUMN_COUNT: Final = 15
REQUIRED_HEADERS: Final[set[str]] = {"Date", "Symbol", "FairMarketValuePrice"}

# Column indices for 2-row format
# Upper row contains these indices
UPPER_ROW_COLUMNS: Final[set[int]] = {0, 1, 2, 3, 4}  # Date, Action, Symbol, Description, Quantity
# Lower row contains these indices
LOWER_ROW_COLUMNS: Final[set[int]] = {8, 9, 10, 11, 12, 13, 14}  # AwardDate onwards
# Indices 5, 6, 7 are empty in both rows


class ValidationError(Exception):
    """CSV validation error."""

    pass


def validate_schwab_awards_csv(
    filepath: Path, verbose: bool = False
) -> tuple[list[str], int]:
    """Validate Schwab awards CSV format and return headers and line count.

    Args:
        filepath: Path to CSV file
        verbose: Enable verbose output

    Returns:
        Tuple of (headers list, data line count)

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
        if len(headers) != EXPECTED_COLUMN_COUNT:
            raise ValidationError(
                f"Expected {EXPECTED_COLUMN_COUNT} columns, got {len(headers)}: {filepath}"
            )

        # Validate required headers
        headers_set = set(headers)
        missing = REQUIRED_HEADERS - headers_set
        if missing:
            raise ValidationError(
                f"Missing required headers {missing}: {filepath}"
            )

        # Count data lines
        lines = list(reader)
        line_count = len(lines)

        # Validate even line count (2-row pairing requirement)
        if line_count % 2 != 0:
            raise ValidationError(
                f"Odd number of data lines ({line_count}), expected even (2-row pairs): {filepath}"
            )

    if verbose:
        print(f"  Headers: {', '.join(headers[:3])}...")
        print(f"  Data lines: {line_count} ({line_count // 2} award pairs)")

    return headers, line_count


def merge_row_pair(upper: list[str], lower: list[str]) -> tuple[str, ...]:
    """Merge upper and lower rows into single row.

    Schwab awards CSV has each award split across 2 rows.
    Upper row has some columns filled, lower row has others.
    Exactly one should be empty for each column position.

    Args:
        upper: First row of pair (15 columns)
        lower: Second row of pair (15 columns)

    Returns:
        Merged row as tuple (immutable)

    Raises:
        ValidationError: If both rows have value in same column
    """
    if len(upper) != EXPECTED_COLUMN_COUNT or len(lower) != EXPECTED_COLUMN_COUNT:
        raise ValidationError(
            f"Invalid row lengths: {len(upper)}, {len(lower)} "
            f"(expected {EXPECTED_COLUMN_COUNT})"
        )

    merged = []
    for i, (upper_col, lower_col) in enumerate(zip(upper, lower)):
        # One must be empty (Schwab format requirement)
        if upper_col != "" and lower_col != "":
            raise ValidationError(
                f"Column {i} has values in both rows: '{upper_col}', '{lower_col}'"
            )
        merged.append(upper_col + lower_col)

    return tuple(merged)  # Immutable for set deduplication


def split_merged_row(merged_row: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Split merged row back into upper/lower pair for output.

    Uses deterministic column pattern:
    - Indices 0-4: Upper row
    - Indices 8-14: Lower row
    - Indices 5-7: Empty in both

    Args:
        merged_row: Merged row tuple (15 columns)

    Returns:
        Tuple of (upper_row, lower_row)

    Raises:
        ValidationError: If row length is invalid
    """
    if len(merged_row) != EXPECTED_COLUMN_COUNT:
        raise ValidationError(f"Invalid merged row length: {len(merged_row)}")

    upper_row = []
    lower_row = []

    for i, value in enumerate(merged_row):
        if i in UPPER_ROW_COLUMNS:
            upper_row.append(value)
            lower_row.append("")
        elif i in LOWER_ROW_COLUMNS:
            upper_row.append("")
            lower_row.append(value)
        else:
            # Columns 5, 6, 7 are empty in both rows
            upper_row.append("")
            lower_row.append("")

    return upper_row, lower_row


def read_schwab_awards_csv(
    filepath: Path,
    reference_headers: list[str],
    verbose: bool = False,
) -> list[tuple[str, ...]]:
    """Read all award pairs from CSV, merge and remap to reference order.

    Args:
        filepath: Path to CSV file
        reference_headers: Header order to use for output
        verbose: Enable verbose output

    Returns:
        List of merged row tuples

    Raises:
        ValidationError: If processing fails
    """
    with filepath.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        lines = list(reader)

    # Create column mapping from file headers to reference headers
    file_header_indices = {header: i for i, header in enumerate(headers)}
    reference_indices = [file_header_indices[header] for header in reference_headers]

    merged_rows = []

    # Process pairs
    for upper, lower in zip(lines[::2], lines[1::2]):
        # Validate column count
        if len(upper) != EXPECTED_COLUMN_COUNT or len(lower) != EXPECTED_COLUMN_COUNT:
            raise ValidationError(
                f"Invalid row column count: {len(upper)}, {len(lower)}"
            )

        # Remap to reference order
        upper_remapped = [upper[i] for i in reference_indices]
        lower_remapped = [lower[i] for i in reference_indices]

        # Merge pair
        merged = merge_row_pair(upper_remapped, lower_remapped)
        merged_rows.append(merged)

    if verbose:
        print(f"  Read {len(merged_rows)} award(s)")

    return merged_rows


def remove_duplicates(
    merged_rows: list[tuple[str, ...]], verbose: bool = False
) -> list[tuple[str, ...]]:
    """Remove duplicate merged rows (full 2-row pair match).

    Deduplication compares entire merged row (all 15 columns).
    If two 2-row pairs merge to identical rows, second is removed.

    Args:
        merged_rows: List of merged row tuples
        verbose: Print duplicate details

    Returns:
        Deduplicated list (preserves first occurrence order)
    """
    seen = set()
    unique_rows = []

    for row in merged_rows:
        if row not in seen:
            seen.add(row)
            unique_rows.append(row)

    duplicates_removed = len(merged_rows) - len(unique_rows)
    if verbose and duplicates_removed > 0:
        print(f"  Removed {duplicates_removed} duplicate award(s)")

    return unique_rows


def parse_date(date_str: str) -> datetime.date | None:
    """Parse Schwab award date (handles two formats).

    Awards CSV uses two date formats:
    - MM/DD/YYYY (e.g., "08/15/2023")
    - YYYY/MM/DD (e.g., "2023/08/15")

    Args:
        date_str: Date string from CSV

    Returns:
        Parsed date or None if parsing fails
    """
    if not date_str:
        return None

    # Try MM/DD/YYYY first (most common)
    try:
        return datetime.datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except ValueError:
        pass

    # Try YYYY/MM/DD
    try:
        return datetime.datetime.strptime(date_str.strip(), "%Y/%m/%d").date()
    except ValueError:
        return None


def sort_by_date(
    merged_rows: list[tuple[str, ...]],
    headers: list[str],
    verbose: bool = False,
) -> list[tuple[str, ...]]:
    """Sort merged rows by Date column (oldest first).

    Args:
        merged_rows: List of merged row tuples
        headers: Column headers in same order as tuples
        verbose: Print warnings for invalid dates

    Returns:
        Sorted list (oldest to newest)
    """
    date_index = headers.index("Date")

    def get_sort_key(row: tuple[str, ...]) -> datetime.date:
        date = parse_date(row[date_index])
        if date is None:
            if verbose:
                print(f"  ⚠ Warning: Invalid date '{row[date_index]}', sorting to end")
            return datetime.date.max
        return date

    return sorted(merged_rows, key=get_sort_key)


def get_date_range(
    merged_rows: list[tuple[str, ...]],
    headers: list[str],
) -> tuple[str, str]:
    """Return (earliest_date_str, latest_date_str).

    Args:
        merged_rows: List of merged row tuples
        headers: Column headers in same order as tuples

    Returns:
        Tuple of (earliest, latest) as strings, or ("N/A", "N/A") if no valid dates
    """
    date_index = headers.index("Date")
    dates = [parse_date(row[date_index]) for row in merged_rows]
    valid_dates = [d for d in dates if d is not None]

    if not valid_dates:
        return ("N/A", "N/A")

    earliest = min(valid_dates)
    latest = max(valid_dates)

    # Return in original format (MM/DD/YYYY)
    return (
        earliest.strftime("%m/%d/%Y"),
        latest.strftime("%m/%d/%Y"),
    )


def write_merged_awards_csv(
    output_path: Path,
    headers: list[str],
    merged_rows: list[tuple[str, ...]],
    verbose: bool = False,
) -> None:
    """Write merged awards to CSV in 2-row format.

    Args:
        output_path: Output file path
        headers: Column headers
        merged_rows: List of merged row tuples
        verbose: Enable verbose output
    """
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Write header
        writer.writerow(headers)

        # Write pairs in interleaved fashion
        for merged_row in merged_rows:
            upper, lower = split_merged_row(merged_row)
            writer.writerow(upper)
            writer.writerow(lower)

    if verbose:
        print(f"  Wrote {len(merged_rows)} award(s) as {len(merged_rows) * 2} rows")


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="Merge multiple Schwab equity awards CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge two award files with auto-generated output name
  %(prog)s account1_awards.csv account2_awards.csv

  # Merge multiple files with specific output name
  %(prog)s -o merged_awards.csv awards1.csv awards2.csv awards3.csv

  # Merge with verbose output
  %(prog)s -v awards1.csv awards2.csv
""",
    )

    parser.add_argument(
        "input_files",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="Schwab equity awards CSV file(s) to merge",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="output filename (default: merged_schwab_awards_TIMESTAMP.csv)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose output",
    )

    return parser


def main() -> int:
    """Main execution flow."""
    parser = create_parser()
    args = parser.parse_args()

    verbose = args.verbose
    input_files = args.input_files

    # Generate timestamp-based output if not specified
    if args.output is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"merged_schwab_awards_{timestamp}.csv")
    else:
        output_path = args.output

    print(f"Merging {len(input_files)} awards file(s)...")
    if verbose:
        print()

    # PHASE 1: Validate all files
    all_headers = []
    all_line_counts = []

    for i, filepath in enumerate(input_files, 1):
        if verbose:
            print(f"Validating file {i}: {filepath}")
        try:
            headers, line_count = validate_schwab_awards_csv(filepath, verbose)
            all_headers.append(headers)
            all_line_counts.append(line_count)
        except ValidationError as e:
            print(f"✗ Error: {e}", file=sys.stderr)
            return 1

    # Check header compatibility
    reference_headers = all_headers[0]
    reference_set = set(reference_headers)

    for i, headers in enumerate(all_headers[1:], 2):
        if set(headers) != reference_set:
            print(
                f"✗ Error: File {i} has different headers than file 1",
                file=sys.stderr,
            )
            return 1

    if verbose:
        print()

    # PHASE 2: Read and merge pairs
    all_merged_rows = []

    for i, filepath in enumerate(input_files, 1):
        if verbose:
            print(f"Reading file {i}: {filepath}")

        try:
            merged_rows = read_schwab_awards_csv(filepath, reference_headers, verbose)
            all_merged_rows.extend(merged_rows)

            print(f"✓ File {i}: {len(merged_rows)} award(s)")
        except ValidationError as e:
            print(f"✗ Error: {e}", file=sys.stderr)
            return 1

    print()
    print(f"Total: {len(all_merged_rows):,} award(s)")

    # PHASE 3: Deduplication
    original_count = len(all_merged_rows)
    all_merged_rows = remove_duplicates(all_merged_rows, verbose=True)
    duplicates_removed = original_count - len(all_merged_rows)

    if duplicates_removed > 0:
        print(f"Removed: {duplicates_removed:,} duplicate(s)")

    # PHASE 4: Sort by date
    all_merged_rows = sort_by_date(all_merged_rows, reference_headers, verbose)

    print(f"Final count: {len(all_merged_rows):,} award(s)")

    # PHASE 5: Get date range
    earliest, latest = get_date_range(all_merged_rows, reference_headers)
    print(f"Date range: {earliest} to {latest}")

    # PHASE 6: Split and write
    try:
        write_merged_awards_csv(output_path, reference_headers, all_merged_rows, verbose)
        print(f"Output: {output_path}")
    except Exception as e:
        print(f"✗ Error writing output: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
