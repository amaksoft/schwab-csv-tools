#!/usr/bin/env python3
"""Merge multiple Schwab transaction CSV files.

This standalone script merges multiple Charles Schwab transaction CSV files
into a single file, with validation, deduplication, and proper sorting.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import sys
from pathlib import Path
from typing import Final

# Schwab CSV required headers
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


class ValidationError(Exception):
    """CSV validation error."""

    pass


def validate_schwab_csv(filepath: Path, verbose: bool = False) -> list[str]:
    """Validate Schwab CSV format and return headers.

    Args:
        filepath: Path to CSV file to validate
        verbose: Print detailed validation info

    Returns:
        List of header strings in file order

    Raises:
        ValidationError: If file format is invalid
    """
    if not filepath.exists():
        raise ValidationError(f"File not found: {filepath}")

    if not filepath.is_file():
        raise ValidationError(f"Not a file: {filepath}")

    try:
        with filepath.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                raise ValidationError(f"Empty CSV file: {filepath}")
    except Exception as e:
        raise ValidationError(f"Error reading {filepath}: {e}")

    # Check column count
    num_cols = len(headers)
    if num_cols < MIN_COLUMNS or num_cols > MAX_COLUMNS:
        raise ValidationError(
            f"Invalid column count in {filepath}: expected {MIN_COLUMNS}-{MAX_COLUMNS}, "
            f"got {num_cols}"
        )

    # Check required headers are present
    headers_set = set(headers)
    missing = REQUIRED_HEADERS - headers_set
    if missing:
        raise ValidationError(
            f"Missing required columns in {filepath}: {missing}"
        )

    if verbose:
        print(f"  ✓ Valid format: {num_cols} columns")

    return headers


def read_schwab_csv(
    filepath: Path,
    reference_headers: list[str],
    verbose: bool = False
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Read all transaction rows from CSV.

    Args:
        filepath: Path to CSV file
        reference_headers: Reference column headers for output order
        verbose: Print detailed info

    Returns:
        Tuple of (file_headers, list of row tuples in reference order)
    """
    rows = []

    with filepath.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        # Read header row
        file_headers = next(reader)

        # Create mapping from file column order to reference order
        column_mapping = []
        for ref_header in reference_headers:
            try:
                column_mapping.append(file_headers.index(ref_header))
            except ValueError:
                # This shouldn't happen if validation passed
                raise ValidationError(
                    f"Missing column '{ref_header}' in {filepath}"
                )

        for row in reader:
            # Skip empty rows
            if not any(row):
                continue

            # Pad row to match file header length if needed
            while len(row) < len(file_headers):
                row.append("")

            # Validate column count
            if len(row) != len(file_headers):
                if verbose:
                    print(f"  ⚠ Warning: Row has {len(row)} columns, expected {len(file_headers)}, skipping")
                continue

            # If 9 columns, verify 9th is empty
            if len(row) == MAX_COLUMNS and row[-1] != "":
                if verbose:
                    print(f"  ⚠ Warning: 9th column not empty, skipping row: {row}")
                continue

            # Remap row to reference column order
            remapped_row = [row[i] for i in column_mapping]
            rows.append(tuple(remapped_row))

    return file_headers, rows


def parse_date(date_str: str) -> datetime.date | None:
    """Parse Schwab date format (MM/DD/YYYY).

    Handles "as of" suffix: "08/18/2023 as of 08/15/2023" -> 08/18/2023

    Args:
        date_str: Date string from CSV

    Returns:
        Parsed date or None if parsing fails
    """
    # Handle "as of" suffix
    as_of_str = " as of "
    if as_of_str in date_str:
        date_str = date_str[:date_str.find(as_of_str)]

    try:
        return datetime.datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def remove_duplicates(rows: list[tuple[str, ...]], verbose: bool = False) -> list[tuple[str, ...]]:
    """Remove exact duplicate rows.

    Args:
        rows: List of row tuples
        verbose: Print duplicate count

    Returns:
        Deduplicated list (preserves first occurrence order)
    """
    seen = set()
    unique_rows = []

    for row in rows:
        if row not in seen:
            seen.add(row)
            unique_rows.append(row)

    duplicates_removed = len(rows) - len(unique_rows)
    if verbose and duplicates_removed > 0:
        print(f"  Removed {duplicates_removed} duplicate(s)")

    return unique_rows


def sort_by_date(
    rows: list[tuple[str, ...]],
    headers: list[str],
    verbose: bool = False
) -> list[tuple[str, ...]]:
    """Sort rows by date (oldest first).

    Args:
        rows: List of row tuples
        headers: List of column headers
        verbose: Print warnings for invalid dates

    Returns:
        Sorted list
    """
    date_index = headers.index("Date")

    def get_sort_key(row: tuple[str, ...]) -> tuple[datetime.date, int]:
        """Get sort key for row (date, original_position).

        Rows with invalid dates sort to end.
        """
        date = parse_date(row[date_index])
        if date is None:
            if verbose:
                print(f"  ⚠ Warning: Invalid date '{row[date_index]}', sorting to end")
            return (datetime.date.max, 0)
        return (date, 0)

    return sorted(rows, key=get_sort_key)


def write_merged_csv(
    output_path: Path,
    headers: list[str],
    rows: list[tuple[str, ...]],
    verbose: bool = False
) -> None:
    """Write merged transactions to output CSV.

    Args:
        output_path: Path for output file
        headers: List of column headers
        rows: List of row tuples
        verbose: Print write info
    """
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)

    if verbose:
        print(f"  Written {len(rows)} row(s) to {output_path}")


def get_date_range(rows: list[tuple[str, ...]], headers: list[str]) -> tuple[str, str]:
    """Get date range from rows.

    Args:
        rows: List of row tuples
        headers: List of column headers

    Returns:
        Tuple of (earliest_date_str, latest_date_str)
    """
    if not rows:
        return ("N/A", "N/A")

    date_index = headers.index("Date")
    dates = []

    for row in rows:
        date = parse_date(row[date_index])
        if date is not None:
            dates.append(date)

    if not dates:
        return ("N/A", "N/A")

    earliest = min(dates)
    latest = max(dates)

    return (earliest.strftime("%m/%d/%Y"), latest.strftime("%m/%d/%Y"))


def parse_quantity(qty_str: str) -> float | None:
    """Parse quantity string (may have commas and negatives).

    Args:
        qty_str: Quantity string from CSV

    Returns:
        Float value or None if empty/invalid
    """
    if not qty_str or qty_str.strip() == "":
        return None

    # Remove commas and convert to float
    try:
        return float(qty_str.replace(",", ""))
    except ValueError:
        return None


def extract_account_number(filename: str) -> str | None:
    """Extract account number from Schwab CSV filename.

    Looks for patterns like:
    - Individual_XXX157_Transactions_... -> 157
    - SCHWAB1_ONE_INTL_XXX964_Transactions_... -> 964

    Args:
        filename: CSV filename (not full path)

    Returns:
        Account number (last 3-4 digits) or None if not found
    """
    import re

    # Pattern: XXX followed by 3-4 digits
    match = re.search(r'XXX(\d{3,4})', filename)
    if match:
        return match.group(1)

    return None


def filter_journaled_shares(
    rows: list[tuple[str, ...]],
    headers: list[str],
    keep_unmatched: bool,
    account_numbers: set[str] | None = None,
    verbose: bool = False
) -> list[tuple[str, ...]]:
    """Filter out matched Journaled Shares and Journal transactions.

    Journaled Shares and Journal transactions represent internal transfers between accounts.
    When merging multiple account files, matched pairs should be removed.

    Matching criteria for Journaled Shares:
    - Action = "Journaled Shares"
    - Same Symbol
    - Same Date
    - Same Price
    - Opposite Quantities (one positive, one negative, same absolute value)

    Matching criteria for Journal transfers:
    - Action = "Journal"
    - Same Date
    - One description contains "JOURNAL TO", other contains "JOURNAL FRM"
    - Opposite Amounts (one positive, one negative, same absolute value)
    - If account_numbers provided: verify the account numbers in descriptions match the input files

    Args:
        rows: All transaction rows
        headers: Column headers
        keep_unmatched: If False, error on unmatched journaled shares
        account_numbers: Set of account numbers from input files (for verification)
        verbose: Print matching details

    Returns:
        Filtered rows with matched pairs removed

    Raises:
        ValidationError: If unmatched journaled shares found and keep_unmatched=False
    """
    # Find column indices
    action_idx = headers.index("Action")
    symbol_idx = headers.index("Symbol")
    date_idx = headers.index("Date")
    price_idx = headers.index("Price")
    quantity_idx = headers.index("Quantity")
    description_idx = headers.index("Description")
    amount_idx = headers.index("Amount")

    # Separate journaled shares and journal transfers from other rows
    journaled_rows = []
    journal_rows = []
    other_rows = []

    for row in rows:
        if row[action_idx] == "Journaled Shares":
            journaled_rows.append(row)
        elif row[action_idx] == "Journal":
            journal_rows.append(row)
        else:
            other_rows.append(row)

    if not journaled_rows and not journal_rows:
        return rows  # No transfers to process, return as-is

    # Process Journaled Shares
    journaled_matched_indices = set()
    journaled_pairs_matched = 0

    if journaled_rows:
        if verbose:
            print(f"Found {len(journaled_rows)} 'Journaled Shares' transaction(s)")

        # Find and remove matching pairs
        for i, row1 in enumerate(journaled_rows):
            if i in journaled_matched_indices:
                continue  # Already matched

            symbol1 = row1[symbol_idx]
            date1 = row1[date_idx]
            price1 = row1[price_idx]
            qty1 = parse_quantity(row1[quantity_idx])

            if qty1 is None:
                continue  # Skip if quantity is missing

            # Search for matching pair
            for j, row2 in enumerate(journaled_rows[i + 1:], start=i + 1):
                if j in journaled_matched_indices:
                    continue  # Already matched

                symbol2 = row2[symbol_idx]
                date2 = row2[date_idx]
                price2 = row2[price_idx]
                qty2 = parse_quantity(row2[quantity_idx])

                if qty2 is None:
                    continue  # Skip if quantity is missing

                # Check if they match
                if (
                    symbol1 == symbol2
                    and date1 == date2
                    and price1 == price2
                    and abs(qty1 + qty2) < 0.01  # Opposite quantities (sum to ~0)
                ):
                    # Found a matching pair!
                    journaled_matched_indices.add(i)
                    journaled_matched_indices.add(j)

                    if verbose:
                        print(f"  Matched pair: {symbol1} on {date1}, qty {qty1} and {qty2}")
                    break  # Found match for row1, move to next

        journaled_pairs_matched = len(journaled_matched_indices) // 2

    # Process Journal transfers
    journal_matched_indices = set()
    journal_pairs_matched = 0

    if journal_rows:
        if verbose:
            print(f"Found {len(journal_rows)} 'Journal' transaction(s)")

        # Helper function to parse amount
        def parse_amount(amt_str: str) -> float | None:
            if not amt_str or amt_str.strip() == "":
                return None
            # Remove $ and commas, convert to float
            try:
                return float(amt_str.replace("$", "").replace(",", ""))
            except ValueError:
                return None

        # Helper function to extract account number from journal description
        def extract_journal_account(desc: str) -> str | None:
            """Extract account number from JOURNAL TO/FRM description.

            Examples:
              "JOURNAL TO ...964" -> "964"
              "JOURNAL FRM ...157" -> "157"
            """
            import re
            # Look for pattern like "...964" or "...157"
            match = re.search(r'\.{3}(\d{3,4})', desc)
            if match:
                return match.group(1)
            return None

        # Find and remove matching pairs
        for i, row1 in enumerate(journal_rows):
            if i in journal_matched_indices:
                continue  # Already matched

            date1 = row1[date_idx]
            desc1 = row1[description_idx].upper()
            amt1 = parse_amount(row1[amount_idx])

            if amt1 is None:
                continue  # Skip if amount is missing

            # Check if this is a TO or FRM transaction
            is_to = "JOURNAL TO" in desc1
            is_frm = "JOURNAL FRM" in desc1

            if not (is_to or is_frm):
                continue  # Not a TO/FRM journal

            # Extract account numbers from description if account verification is enabled
            acct1 = extract_journal_account(desc1) if account_numbers else None

            # Search for matching pair
            for j, row2 in enumerate(journal_rows[i + 1:], start=i + 1):
                if j in journal_matched_indices:
                    continue  # Already matched

                date2 = row2[date_idx]
                desc2 = row2[description_idx].upper()
                amt2 = parse_amount(row2[amount_idx])

                if amt2 is None:
                    continue  # Skip if amount is missing

                # Check if dates match and descriptions are opposite types
                if date1 == date2:
                    # One should be TO and the other FRM
                    if is_to and "JOURNAL FRM" in desc2:
                        # Check if amounts are opposite
                        if abs(amt1 + amt2) < 0.01:  # Sum to ~0
                            # If account numbers are available, verify they match our input files
                            if account_numbers:
                                acct2 = extract_journal_account(desc2)
                                # Both accounts should be in our input files
                                if acct1 and acct2:
                                    if acct1 not in account_numbers or acct2 not in account_numbers:
                                        if verbose:
                                            print(f"  Skipping Journal pair on {date1}: accounts {acct1}, {acct2} not in input files ({account_numbers})")
                                        continue  # Skip this pair - accounts don't match input files

                            journal_matched_indices.add(i)
                            journal_matched_indices.add(j)
                            if verbose:
                                if account_numbers and acct1 and acct2:
                                    print(f"  Matched Journal pair on {date1}, amounts {amt1} and {amt2}, accounts {acct1}↔{acct2}")
                                else:
                                    print(f"  Matched Journal pair on {date1}, amounts {amt1} and {amt2}")
                            break
                    elif is_frm and "JOURNAL TO" in desc2:
                        # Check if amounts are opposite
                        if abs(amt1 + amt2) < 0.01:  # Sum to ~0
                            # If account numbers are available, verify they match our input files
                            if account_numbers:
                                acct2 = extract_journal_account(desc2)
                                # Both accounts should be in our input files
                                if acct1 and acct2:
                                    if acct1 not in account_numbers or acct2 not in account_numbers:
                                        if verbose:
                                            print(f"  Skipping Journal pair on {date1}: accounts {acct1}, {acct2} not in input files ({account_numbers})")
                                        continue  # Skip this pair - accounts don't match input files

                            journal_matched_indices.add(i)
                            journal_matched_indices.add(j)
                            if verbose:
                                if account_numbers and acct1 and acct2:
                                    print(f"  Matched Journal pair on {date1}, amounts {amt1} and {amt2}, accounts {acct1}↔{acct2}")
                                else:
                                    print(f"  Matched Journal pair on {date1}, amounts {amt1} and {amt2}")
                            break

        journal_pairs_matched = len(journal_matched_indices) // 2

    # Check for unmatched journaled shares and journals
    journaled_unmatched = set(range(len(journaled_rows))) - journaled_matched_indices
    journal_unmatched = set(range(len(journal_rows))) - journal_matched_indices

    # Helper function to extract account number (reuse from above if needed)
    def extract_journal_account(desc: str) -> str | None:
        """Extract account number from JOURNAL TO/FRM description."""
        import re
        match = re.search(r'\.{3}(\d{3,4})', desc)
        if match:
            return match.group(1)
        return None

    # If we have account numbers, check if unmatched journals involve our accounts
    if account_numbers and journal_unmatched and not keep_unmatched:
        problematic_journals = []
        for idx in journal_unmatched:
            row = journal_rows[idx]
            desc = row[description_idx]
            acct = extract_journal_account(desc)
            # If this journal mentions one of our accounts, it's problematic
            if acct and acct in account_numbers:
                problematic_journals.append((idx, row, acct))

        if problematic_journals:
            # Build error message
            error_msg = f"{len(problematic_journals)} unmatched journal transfer(s) found involving accounts {sorted(account_numbers)} "
            error_msg += "(use --keep-unmatched-transfers to keep them):\n"
            for idx, row, acct in problematic_journals:
                error_msg += f"  {row[date_idx]}, {row[description_idx]}, amt {row[amount_idx]}, account {acct}\n"
            raise ValidationError(error_msg.rstrip())

    # Original unmatched checking (for cases without account verification or for journaled shares)
    total_unmatched = len(journaled_unmatched) + len(journal_unmatched)

    if total_unmatched > 0 and not keep_unmatched:
        # Only error on non-journal unmatched if we don't have account verification
        # (journals with account verification are handled above)
        if journaled_unmatched or (journal_unmatched and not account_numbers):
            error_msg = f"{total_unmatched} unmatched transfer(s) found "
            error_msg += "(use --keep-unmatched-transfers to keep them):\n"

            if journaled_unmatched:
                error_msg += "  Journaled Shares:\n"
                for idx in sorted(journaled_unmatched):
                    row = journaled_rows[idx]
                    error_msg += f"    {row[date_idx]}, {row[symbol_idx]}, qty {row[quantity_idx]}\n"

            if journal_unmatched and not account_numbers:
                error_msg += "  Journal transfers:\n"
                for idx in sorted(journal_unmatched):
                    row = journal_rows[idx]
                    error_msg += f"    {row[date_idx]}, {row[description_idx]}, amt {row[amount_idx]}\n"

            raise ValidationError(error_msg.rstrip())

    if verbose and total_unmatched > 0:
        unmatched_count = total_unmatched
        # If we have account numbers, only count non-account-related journals as "kept"
        if account_numbers and journal_unmatched:
            non_account_journals = 0
            for idx in journal_unmatched:
                row = journal_rows[idx]
                desc = row[description_idx]
                acct = extract_journal_account(desc)
                if not acct or acct not in account_numbers:
                    non_account_journals += 1
            unmatched_count = len(journaled_unmatched) + non_account_journals

        if unmatched_count > 0:
            print(f"  Keeping {unmatched_count} unmatched transfer(s) not involving merge accounts")

    # Build result: other rows + unmatched transfers (if keeping)
    result = other_rows

    if keep_unmatched:
        if journaled_unmatched:
            for idx in sorted(journaled_unmatched):
                result.append(journaled_rows[idx])
        if journal_unmatched:
            for idx in sorted(journal_unmatched):
                result.append(journal_rows[idx])

    # Print summary
    total_found = len(journaled_rows) + len(journal_rows)
    total_pairs = journaled_pairs_matched + journal_pairs_matched
    total_removed = len(journaled_matched_indices) + len(journal_matched_indices)

    if journaled_rows:
        print(f"Journaled Shares: {len(journaled_rows)} found, {journaled_pairs_matched} pair(s) matched, {len(journaled_matched_indices)} removed")
    if journal_rows:
        print(f"Journal transfers: {len(journal_rows)} found, {journal_pairs_matched} pair(s) matched, {len(journal_matched_indices)} removed")

    return result


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="Merge multiple Charles Schwab transaction CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge two files with auto-generated output name
  %(prog)s account1.csv account2.csv

  # Merge multiple files with specific output name
  %(prog)s -o merged.csv account1.csv account2.csv account3.csv

  # Merge with verbose output
  %(prog)s -v account1.csv account2.csv
""",
    )

    parser.add_argument(
        "input_files",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="Schwab transaction CSV file(s) to merge",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="output filename (default: merged_schwab_TIMESTAMP.csv)",
    )

    parser.add_argument(
        "--keep-unmatched-transfers",
        action="store_true",
        help="keep unmatched 'Journaled Shares' instead of erroring",
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

    # Generate output filename if not specified
    if args.output is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"merged_schwab_{timestamp}.csv")
    else:
        output_path = args.output

    print(f"Processing {len(input_files)} input file(s)...")
    print()

    # Step 1: Validate all files and collect headers
    all_headers = []
    for i, filepath in enumerate(input_files, 1):
        if verbose:
            print(f"Validating file {i}: {filepath}")
        try:
            headers = validate_schwab_csv(filepath, verbose)
            all_headers.append(headers)
        except ValidationError as e:
            print(f"✗ Error: {e}", file=sys.stderr)
            return 1

    # Step 2: Check all files have compatible header structure (same headers, any order)
    reference_headers = all_headers[0]
    reference_headers_set = set(reference_headers)

    for i, headers in enumerate(all_headers[1:], 2):
        headers_set = set(headers)
        if headers_set != reference_headers_set:
            missing = reference_headers_set - headers_set
            extra = headers_set - reference_headers_set
            print(
                f"✗ Error: File {i} has different columns than file 1",
                file=sys.stderr,
            )
            if missing:
                print(f"  Missing: {missing}", file=sys.stderr)
            if extra:
                print(f"  Extra: {extra}", file=sys.stderr)
            return 1

    if verbose:
        print()

    # Step 3: Read all rows from all files (normalizing to reference column order)
    all_rows = []
    file_counts = []

    for i, filepath in enumerate(input_files, 1):
        if verbose:
            print(f"Reading file {i}: {filepath}")

        file_headers, rows = read_schwab_csv(filepath, reference_headers, verbose)
        all_rows.extend(rows)
        file_counts.append(len(rows))

        symbol = "✓"
        print(f"{symbol} File {i}: {len(rows):,} transaction(s)")

        if verbose and list(file_headers) != reference_headers:
            print(f"  (Remapped from: {file_headers})")

    print()
    print(f"Total: {len(all_rows):,} transaction(s)")

    # Step 4: Remove duplicates
    original_count = len(all_rows)
    all_rows = remove_duplicates(all_rows, verbose=True)
    duplicates_removed = original_count - len(all_rows)

    if duplicates_removed > 0:
        print(f"Removed: {duplicates_removed:,} duplicate(s)")

    # Extract account numbers from filenames for journal transfer verification
    account_numbers = set()
    missing_account_info = []

    for filepath in input_files:
        filename = filepath.name
        acct_num = extract_account_number(filename)
        if acct_num:
            account_numbers.add(acct_num)
        else:
            missing_account_info.append(filename)

    # Only use account verification if we could extract account numbers from ALL files
    if missing_account_info:
        if verbose:
            print(f"⚠ Warning: Could not extract account numbers from {len(missing_account_info)} file(s):")
            for fname in missing_account_info:
                print(f"    {fname}")
            print("  Skipping account verification for journal transfers")
            print()
        account_numbers = None  # Disable account verification
    else:
        if verbose:
            print(f"Detected account numbers: {sorted(account_numbers)}")
            print()

    # Step 4.5: Filter Journaled Shares
    try:
        all_rows = filter_journaled_shares(
            all_rows,
            reference_headers,
            args.keep_unmatched_transfers,
            account_numbers,
            verbose
        )
    except ValidationError as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        return 1

    # Step 5: Sort by date
    all_rows = sort_by_date(all_rows, reference_headers, verbose)

    print(f"Final count: {len(all_rows):,} transaction(s)")

    # Step 6: Get date range
    earliest, latest = get_date_range(all_rows, reference_headers)
    print(f"Date range: {earliest} to {latest}")

    # Step 7: Write output
    try:
        write_merged_csv(output_path, reference_headers, all_rows, verbose)
        print(f"Output: {output_path}")
    except Exception as e:
        print(f"✗ Error writing output file: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
