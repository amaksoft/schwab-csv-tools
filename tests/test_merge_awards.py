#!/usr/bin/env python3
"""Tests for merge_awards.py module.

Tests cover:
- CSV validation (15-column format)
- 2-row pair merging
- Deduplication
- Date sorting
- Row splitting back to 2-row format
"""

import csv
import tempfile
from pathlib import Path

import pytest


class TestAwardsCSVValidation:
    """Test awards CSV format validation."""

    def test_valid_awards_csv(self):
        """Test validation of valid Schwab awards CSV."""
        from schwab_csv_tools.merge_awards import validate_schwab_awards_csv

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            # Write 15-column header
            writer.writerow([
                "Date", "Action", "Symbol", "Description", "Quantity",
                "", "", "",  # Empty columns 5-7
                "AwardDate", "AwardId", "AwardName", "FairMarketValuePrice",
                "PurchasePrice", "Quantity", "NetSharesDeposited"
            ])
            # Write 2-row pair
            writer.writerow([
                "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC CLASS A", "81",
                "", "", "", "", "", "", "", "", "", ""
            ])
            writer.writerow([
                "", "", "", "", "",
                "", "", "",
                "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
            ])
            input_file = Path(f.name)

        try:
            headers, line_count = validate_schwab_awards_csv(input_file, verbose=False)
            assert len(headers) == 15
            assert line_count == 2  # 2 rows (1 pair)
            assert "Date" in headers
            assert "FairMarketValuePrice" in headers
        finally:
            input_file.unlink()

    def test_invalid_column_count(self):
        """Test validation fails with wrong column count."""
        from schwab_csv_tools.merge_awards import (
            validate_schwab_awards_csv,
            ValidationError,
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            # Only 8 columns instead of 15
            writer.writerow([
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            input_file = Path(f.name)

        try:
            with pytest.raises(ValidationError, match="Expected 15 columns"):
                validate_schwab_awards_csv(input_file, verbose=False)
        finally:
            input_file.unlink()

    def test_odd_line_count(self):
        """Test validation fails with odd line count (unpaired rows)."""
        from schwab_csv_tools.merge_awards import (
            validate_schwab_awards_csv,
            ValidationError,
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", "Action", "Symbol", "Description", "Quantity",
                "", "", "",
                "AwardDate", "AwardId", "AwardName", "FairMarketValuePrice",
                "PurchasePrice", "Quantity", "NetSharesDeposited"
            ])
            # Only 1 row instead of a pair
            writer.writerow([
                "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
                "", "", "", "", "", "", "", "", "", ""
            ])
            input_file = Path(f.name)

        try:
            with pytest.raises(ValidationError, match="Odd number of data lines"):
                validate_schwab_awards_csv(input_file, verbose=False)
        finally:
            input_file.unlink()

    def test_missing_required_headers(self):
        """Test validation fails with missing required headers."""
        from schwab_csv_tools.merge_awards import (
            validate_schwab_awards_csv,
            ValidationError,
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            # Missing "FairMarketValuePrice"
            writer.writerow([
                "Date", "Action", "Symbol", "Description", "Quantity",
                "", "", "",
                "AwardDate", "AwardId", "AwardName", "OtherColumn",
                "PurchasePrice", "Quantity", "NetSharesDeposited"
            ])
            input_file = Path(f.name)

        try:
            with pytest.raises(ValidationError, match="Missing required headers"):
                validate_schwab_awards_csv(input_file, verbose=False)
        finally:
            input_file.unlink()


class TestRowPairMerging:
    """Test 2-row pair merging logic."""

    def test_merge_row_pair(self):
        """Test merging upper and lower rows into single row."""
        from schwab_csv_tools.merge_awards import merge_row_pair

        upper = [
            "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
            "", "", "", "", "", "", "", "", "", ""
        ]
        lower = [
            "", "", "", "", "",
            "", "", "",
            "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
        ]

        merged = merge_row_pair(upper, lower)

        assert len(merged) == 15
        assert merged[0] == "11/15/2021"  # From upper
        assert merged[2] == "META"  # From upper
        assert merged[8] == "11/15/2021"  # From lower
        assert merged[11] == "$338.54"  # From lower

    def test_merge_row_pair_conflict(self):
        """Test merging fails when both rows have value in same column."""
        from schwab_csv_tools.merge_awards import (
            merge_row_pair,
            ValidationError,
        )

        upper = [
            "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
            "", "", "", "", "", "", "", "", "", ""
        ]
        lower = [
            "CONFLICT", "", "", "", "",  # Conflict in column 0
            "", "", "",
            "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
        ]

        with pytest.raises(ValidationError, match="has values in both rows"):
            merge_row_pair(upper, lower)


class TestRowSplitting:
    """Test splitting merged row back to 2-row format."""

    def test_split_merged_row(self):
        """Test splitting merged row into upper/lower pair."""
        from schwab_csv_tools.merge_awards import split_merged_row

        merged = (
            "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
            "", "", "",
            "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
        )

        upper, lower = split_merged_row(merged)

        # Upper row should have columns 0-4 filled, rest empty
        assert upper[0] == "11/15/2021"
        assert upper[2] == "META"
        assert upper[4] == "81"
        assert upper[8] == ""  # Empty in upper

        # Lower row should have columns 8-14 filled, rest empty
        assert lower[0] == ""  # Empty in lower
        assert lower[8] == "11/15/2021"
        assert lower[11] == "$338.54"


class TestAwardsDeduplication:
    """Test award deduplication logic."""

    def test_remove_duplicate_awards(self):
        """Test removal of duplicate award pairs."""
        from schwab_csv_tools.merge_awards import remove_duplicates

        # Create duplicate merged rows
        award1 = (
            "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
            "", "", "",
            "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
        )
        award2 = (
            "11/20/2021", "Stock Plan Activity", "AAPL", "APPLE INC", "50",
            "", "", "",
            "11/20/2021", "789012", "RSU AWARD", "$150.00", "$0.00", "100", "50"
        )
        award3 = (
            "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
            "", "", "",
            "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
        )  # Duplicate of award1

        merged_rows = [award1, award2, award3]
        unique_rows = remove_duplicates(merged_rows, verbose=False)

        assert len(unique_rows) == 2
        assert award1 in unique_rows
        assert award2 in unique_rows


class TestAwardsDateSorting:
    """Test award date sorting."""

    def test_sort_awards_by_date(self):
        """Test awards are sorted by date (oldest first)."""
        from schwab_csv_tools.merge_awards import sort_by_date

        headers = [
            "Date", "Action", "Symbol", "Description", "Quantity",
            "", "", "",
            "AwardDate", "AwardId", "AwardName", "FairMarketValuePrice",
            "PurchasePrice", "Quantity", "NetSharesDeposited"
        ]

        awards = [
            (
                "03/20/2022", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
                "", "", "",
                "03/20/2022", "333333", "RSU AWARD", "$200.00", "$0.00", "162", "81"
            ),
            (
                "01/15/2022", "Stock Plan Activity", "AAPL", "APPLE INC", "50",
                "", "", "",
                "01/15/2022", "111111", "RSU AWARD", "$150.00", "$0.00", "100", "50"
            ),
            (
                "02/10/2022", "Stock Plan Activity", "MSFT", "MICROSOFT CORP", "30",
                "", "", "",
                "02/10/2022", "222222", "RSU AWARD", "$250.00", "$0.00", "60", "30"
            ),
        ]

        sorted_awards = sort_by_date(awards, headers, verbose=False)

        # Should be sorted: 01/15, 02/10, 03/20
        assert sorted_awards[0][0] == "01/15/2022"
        assert sorted_awards[1][0] == "02/10/2022"
        assert sorted_awards[2][0] == "03/20/2022"

    def test_parse_date_formats(self):
        """Test parsing both MM/DD/YYYY and YYYY/MM/DD formats."""
        from schwab_csv_tools.merge_awards import parse_date

        # Test MM/DD/YYYY format
        date1 = parse_date("11/15/2021")
        assert date1.year == 2021
        assert date1.month == 11
        assert date1.day == 15

        # Test YYYY/MM/DD format
        date2 = parse_date("2021/11/15")
        assert date2.year == 2021
        assert date2.month == 11
        assert date2.day == 15

        # Test invalid format
        date3 = parse_date("invalid")
        assert date3 is None


class TestAwardsDateRange:
    """Test date range calculation for awards."""

    def test_get_awards_date_range(self):
        """Test calculating date range from awards."""
        from schwab_csv_tools.merge_awards import get_date_range

        headers = [
            "Date", "Action", "Symbol", "Description", "Quantity",
            "", "", "",
            "AwardDate", "AwardId", "AwardName", "FairMarketValuePrice",
            "PurchasePrice", "Quantity", "NetSharesDeposited"
        ]

        awards = [
            (
                "03/20/2022", "Stock Plan Activity", "META", "META", "81",
                "", "", "",
                "03/20/2022", "333", "RSU", "$200.00", "$0.00", "162", "81"
            ),
            (
                "01/15/2022", "Stock Plan Activity", "AAPL", "APPLE", "50",
                "", "", "",
                "01/15/2022", "111", "RSU", "$150.00", "$0.00", "100", "50"
            ),
        ]

        earliest, latest = get_date_range(awards, headers)

        assert earliest == "01/15/2022"
        assert latest == "03/20/2022"

    def test_get_awards_date_range_empty(self):
        """Test date range with no awards."""
        from schwab_csv_tools.merge_awards import get_date_range

        headers = [
            "Date", "Action", "Symbol", "Description", "Quantity",
            "", "", "",
            "AwardDate", "AwardId", "AwardName", "FairMarketValuePrice",
            "PurchasePrice", "Quantity", "NetSharesDeposited"
        ]

        earliest, latest = get_date_range([], headers)

        assert earliest == "N/A"
        assert latest == "N/A"


class TestAwardsReadWrite:
    """Test reading and writing awards files."""

    def test_read_and_write_awards(self):
        """Test round-trip: read awards, process, write back."""
        from schwab_csv_tools.merge_awards import (
            read_schwab_awards_csv,
            write_merged_awards_csv,
        )

        headers = [
            "Date", "Action", "Symbol", "Description", "Quantity",
            "", "", "",
            "AwardDate", "AwardId", "AwardName", "FairMarketValuePrice",
            "PurchasePrice", "Quantity", "NetSharesDeposited"
        ]

        # Create input file with 2-row pair
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerow([
                "11/15/2021", "Stock Plan Activity", "META", "META PLATFORMS INC", "81",
                "", "", "", "", "", "", "", "", "", ""
            ])
            writer.writerow([
                "", "", "", "", "",
                "", "", "",
                "11/15/2021", "123456", "RSU AWARD", "$338.54", "$0.00", "162", "81"
            ])
            input_file = Path(f.name)

        output_file = input_file.parent / f"{input_file.stem}_output.csv"

        try:
            # Read awards
            merged_rows = read_schwab_awards_csv(input_file, headers, verbose=False)
            assert len(merged_rows) == 1

            # Write awards
            write_merged_awards_csv(output_file, headers, merged_rows, verbose=False)

            # Verify output file exists and has correct row count
            assert output_file.exists()

            # Read back and verify
            with output_file.open() as f:
                reader = csv.reader(f)
                output_headers = next(reader)
                output_rows = list(reader)

            assert output_headers == headers
            assert len(output_rows) == 2  # 2-row pair

        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()
