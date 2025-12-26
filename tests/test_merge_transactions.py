#!/usr/bin/env python3
"""Tests for merge_transactions.py module.

Tests cover:
- CSV validation
- Transaction merging
- Deduplication
- Date sorting
- Journaled Shares matching
- Journal transfer matching
- Account number verification
"""

import csv
import tempfile
from pathlib import Path

import pytest


class TestCSVValidation:
    """Test CSV format validation."""

    def test_valid_csv_format(self):
        """Test validation of valid Schwab transaction CSV."""
        from schwab_csv_tools.merge_transactions import validate_schwab_csv

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writerow([
                "01/15/2024", "Buy", "AAPL", "APPLE INC",
                "$150.00", "10", "$1.00", "-$1,501.00"
            ])
            input_file = Path(f.name)

        try:
            headers = validate_schwab_csv(input_file, verbose=False)
            assert len(headers) == 8
            assert "Date" in headers
            assert "Amount" in headers
        finally:
            input_file.unlink()

    def test_missing_required_headers(self):
        """Test validation fails with missing required headers."""
        from schwab_csv_tools.merge_transactions import (
            ValidationError,
            validate_schwab_csv,
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            # 8 columns but missing "Symbol" - has wrong header
            writer.writerow([
                "Date", "Action", "WrongHeader", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            input_file = Path(f.name)

        try:
            with pytest.raises(ValidationError, match="Missing required columns"):
                validate_schwab_csv(input_file, verbose=False)
        finally:
            input_file.unlink()

    def test_invalid_column_count(self):
        """Test validation fails with wrong column count."""
        from schwab_csv_tools.merge_transactions import (
            ValidationError,
            validate_schwab_csv,
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            # Only 5 columns instead of 8
            writer.writerow(["Date", "Action", "Symbol", "Description", "Price"])
            input_file = Path(f.name)

        try:
            with pytest.raises(ValidationError, match="Invalid column count"):
                validate_schwab_csv(input_file, verbose=False)
        finally:
            input_file.unlink()


class TestTransactionMerging:
    """Test transaction merging functionality."""

    def test_merge_two_files(self):
        """Test merging two transaction files."""
        from schwab_csv_tools.merge_transactions import (
            read_schwab_csv,
            remove_duplicates,
            validate_schwab_csv,
        )

        # Create first file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writerow([
                "01/15/2024", "Buy", "AAPL", "APPLE INC",
                "$150.00", "10", "$1.00", "-$1,501.00"
            ])
            file1 = Path(f.name)

        # Create second file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writerow([
                "01/20/2024", "Sell", "AAPL", "APPLE INC",
                "$155.00", "5", "$1.00", "$774.00"
            ])
            file2 = Path(f.name)

        try:
            headers1 = validate_schwab_csv(file1)
            headers2 = validate_schwab_csv(file2)

            _, rows1 = read_schwab_csv(file1, headers1)
            _, rows2 = read_schwab_csv(file2, headers2)

            all_rows = rows1 + rows2
            assert len(all_rows) == 2

            # Test deduplication
            unique_rows = remove_duplicates(all_rows)
            assert len(unique_rows) == 2

        finally:
            file1.unlink()
            file2.unlink()

    def test_deduplication(self):
        """Test removal of duplicate transactions."""
        from schwab_csv_tools.merge_transactions import remove_duplicates

        # Create duplicate rows
        row1 = ("01/15/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00")
        row2 = ("01/20/2024", "Sell", "AAPL", "APPLE INC", "$155.00", "5", "$1.00", "$774.00")
        row3 = ("01/15/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00")  # Duplicate of row1

        rows = [row1, row2, row3]
        unique_rows = remove_duplicates(rows, verbose=False)

        assert len(unique_rows) == 2
        assert row1 in unique_rows
        assert row2 in unique_rows


class TestJournaledSharesMatching:
    """Test Journaled Shares matching logic."""

    def test_match_journaled_shares_pair(self):
        """Test matching a pair of Journaled Shares transactions."""
        from schwab_csv_tools.merge_transactions import filter_journaled_shares

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        # Create matching pair: opposite quantities, same date/symbol/price
        rows = [
            ("08/18/2024", "Journaled Shares", "META", "META PLATFORMS INC", "$475.00", "-161", "", ""),
            ("08/18/2024", "Journaled Shares", "META", "META PLATFORMS INC", "$475.00", "161", "", ""),
            ("01/20/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00"),
        ]

        result = filter_journaled_shares(rows, headers, keep_unmatched=False, verbose=False)

        # Should have removed the matched pair, kept the Buy
        assert len(result) == 1
        assert result[0][1] == "Buy"  # Action column

    def test_unmatched_journaled_shares_error(self):
        """Test error on unmatched Journaled Shares."""
        from schwab_csv_tools.merge_transactions import (
            ValidationError,
            filter_journaled_shares,
        )

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        # Single unmatched Journaled Shares
        rows = [
            ("08/18/2024", "Journaled Shares", "META", "META PLATFORMS INC", "$475.00", "-161", "", ""),
        ]

        with pytest.raises(ValidationError, match="unmatched transfer"):
            filter_journaled_shares(rows, headers, keep_unmatched=False, verbose=False)

    def test_keep_unmatched_journaled_shares(self):
        """Test keeping unmatched Journaled Shares with flag."""
        from schwab_csv_tools.merge_transactions import filter_journaled_shares

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        # Single unmatched Journaled Shares
        rows = [
            ("08/18/2024", "Journaled Shares", "META", "META PLATFORMS INC", "$475.00", "-161", "", ""),
            ("01/20/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00"),
        ]

        result = filter_journaled_shares(rows, headers, keep_unmatched=True, verbose=False)

        # Should keep both rows
        assert len(result) == 2


class TestJournalTransferMatching:
    """Test Journal transfer matching logic."""

    def test_match_journal_transfer_pair(self):
        """Test matching a pair of Journal transfers (TO/FRM)."""
        from schwab_csv_tools.merge_transactions import filter_journaled_shares

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        # Create matching pair: opposite amounts, TO/FRM on same date
        rows = [
            ("02/20/2025", "Journal", "", "JOURNAL TO ...964", "", "", "", "-$100,000.00"),
            ("02/20/2025", "Journal", "", "JOURNAL FRM ...157", "", "", "", "$100,000.00"),
            ("01/20/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00"),
        ]

        result = filter_journaled_shares(rows, headers, keep_unmatched=False, verbose=False)

        # Should have removed the matched pair, kept the Buy
        assert len(result) == 1
        assert result[0][1] == "Buy"

    def test_journal_with_account_verification(self):
        """Test Journal matching with account number verification."""
        from schwab_csv_tools.merge_transactions import filter_journaled_shares

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        # Matching pair with accounts 157 and 964
        rows = [
            ("02/20/2025", "Journal", "", "JOURNAL TO ...964", "", "", "", "-$100,000.00"),
            ("02/20/2025", "Journal", "", "JOURNAL FRM ...157", "", "", "", "$100,000.00"),
        ]

        # Both accounts in merge set - should match
        result = filter_journaled_shares(
            rows, headers, keep_unmatched=False,
            account_numbers={"157", "964"}, verbose=False
        )
        assert len(result) == 0  # Both removed

    def test_journal_account_verification_mismatch(self):
        """Test Journal matching skips pairs with accounts not in merge set."""
        from schwab_csv_tools.merge_transactions import filter_journaled_shares

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        # Pair with accounts 157 and 999 (999 not in merge set)
        rows = [
            ("02/20/2025", "Journal", "", "JOURNAL TO ...999", "", "", "", "-$100,000.00"),
            ("02/20/2025", "Journal", "", "JOURNAL FRM ...157", "", "", "", "$100,000.00"),
        ]

        # Only account 157 in merge set - should keep both (not match)
        result = filter_journaled_shares(
            rows, headers, keep_unmatched=True,
            account_numbers={"157"}, verbose=False
        )
        assert len(result) == 2  # Both kept


class TestDateSorting:
    """Test date sorting functionality."""

    def test_sort_by_date(self):
        """Test transactions are sorted by date (oldest first)."""
        from schwab_csv_tools.merge_transactions import sort_by_date

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        rows = [
            ("03/20/2024", "Sell", "AAPL", "APPLE INC", "$155.00", "5", "$1.00", "$774.00"),
            ("01/15/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00"),
            ("02/10/2024", "Buy", "MSFT", "MICROSOFT CORP", "$250.00", "5", "$1.00", "-$1,251.00"),
        ]

        sorted_rows = sort_by_date(rows, headers, verbose=False)

        # Should be sorted: 01/15, 02/10, 03/20
        assert sorted_rows[0][0] == "01/15/2024"
        assert sorted_rows[1][0] == "02/10/2024"
        assert sorted_rows[2][0] == "03/20/2024"


class TestAccountNumberExtraction:
    """Test account number extraction from filenames."""

    def test_extract_account_from_filename(self):
        """Test extracting account number from Schwab filename."""
        from schwab_csv_tools.common import extract_account_number

        # Test various filename patterns
        assert extract_account_number("Individual_XXX157_Transactions_20251114.csv") == "157"
        assert extract_account_number("SCHWAB1_ONE_INTL_XXX964_Transactions_20251114.csv") == "964"
        assert extract_account_number("XXX1234_Transactions.csv") == "1234"
        assert extract_account_number("transactions.csv") is None

    def test_extract_journal_account(self):
        """Test extracting account number from Journal description."""
        from schwab_csv_tools.common import extract_journal_account

        assert extract_journal_account("JOURNAL TO ...964") == "964"
        assert extract_journal_account("JOURNAL FRM ...157") == "157"
        assert extract_journal_account("JOURNAL TO ...1234") == "1234"
        assert extract_journal_account("Regular transaction") is None


class TestDateRange:
    """Test date range calculation."""

    def test_get_date_range(self):
        """Test calculating date range from transactions."""
        from schwab_csv_tools.merge_transactions import get_date_range

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        rows = [
            ("03/20/2024", "Sell", "AAPL", "APPLE INC", "$155.00", "5", "$1.00", "$774.00"),
            ("01/15/2024", "Buy", "AAPL", "APPLE INC", "$150.00", "10", "$1.00", "-$1,501.00"),
            ("02/10/2024", "Buy", "MSFT", "MICROSOFT CORP", "$250.00", "5", "$1.00", "-$1,251.00"),
        ]

        earliest, latest = get_date_range(rows, headers)

        assert earliest == "01/15/2024"
        assert latest == "03/20/2024"

    def test_get_date_range_empty(self):
        """Test date range with no rows."""
        from schwab_csv_tools.merge_transactions import get_date_range

        headers = [
            "Date", "Action", "Symbol", "Description",
            "Price", "Quantity", "Fees & Comm", "Amount"
        ]

        earliest, latest = get_date_range([], headers)

        assert earliest == "N/A"
        assert latest == "N/A"
