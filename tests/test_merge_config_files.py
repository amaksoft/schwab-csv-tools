"""Tests for merge_config_files module."""

import csv
import tempfile
from pathlib import Path

import pytest


class TestMergeInitialPrices:
    """Tests for merge_initial_prices function."""

    def test_merge_two_files(self):
        """Test merging two initial prices files."""
        from schwab_csv_tools.merge_config_files import merge_initial_prices

        # Create first file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["date", "symbol", "price"])
            writer.writerow(["May 30, 2025", "AMTM", "29.72"])
            writer.writerow(["May 30, 2025", "J", "125.72"])
            file1 = Path(f1.name)

        # Create second file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f2:
            writer = csv.writer(f2)
            writer.writerow(["date", "symbol", "price"])
            writer.writerow(["June 1, 2025", "AAPL", "180.50"])
            file2 = Path(f2.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_initial_prices([file1, file2], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have 3 rows
            assert len(rows) == 3

            # Check rows are sorted
            assert rows[0]["symbol"] == "AAPL"
            assert rows[0]["date"] == "June 1, 2025"
            assert rows[1]["symbol"] == "AMTM"
            assert rows[2]["symbol"] == "J"

        finally:
            file1.unlink(missing_ok=True)
            file2.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_deduplication_keeps_last(self):
        """Test that duplicates are deduplicated, keeping last occurrence."""
        from schwab_csv_tools.merge_config_files import merge_initial_prices

        # Create first file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["date", "symbol", "price"])
            writer.writerow(["May 30, 2025", "AMTM", "29.72"])
            file1 = Path(f1.name)

        # Create second file with duplicate
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f2:
            writer = csv.writer(f2)
            writer.writerow(["date", "symbol", "price"])
            writer.writerow(["May 30, 2025", "AMTM", "30.00"])
            file2 = Path(f2.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_initial_prices([file1, file2], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have only 1 row
            assert len(rows) == 1
            # Should keep last occurrence
            assert rows[0]["price"] == "30.00"

        finally:
            file1.unlink(missing_ok=True)
            file2.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_empty_files(self):
        """Test merging empty files."""
        from schwab_csv_tools.merge_config_files import merge_initial_prices

        # Create empty file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["date", "symbol", "price"])
            file1 = Path(f1.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_initial_prices([file1], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have no rows
            assert len(rows) == 0

        finally:
            file1.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_multiple_duplicates(self):
        """Test that multiple duplicates are all deduplicated."""
        from schwab_csv_tools.merge_config_files import merge_initial_prices

        # Create first file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["date", "symbol", "price"])
            writer.writerow(["May 30, 2025", "AMTM", "29.72"])
            writer.writerow(["May 30, 2025", "J", "125.72"])
            file1 = Path(f1.name)

        # Create second file with duplicates
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f2:
            writer = csv.writer(f2)
            writer.writerow(["date", "symbol", "price"])
            writer.writerow(["May 30, 2025", "AMTM", "30.00"])
            writer.writerow(["May 30, 2025", "J", "126.00"])
            file2 = Path(f2.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_initial_prices([file1, file2], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have 2 rows
            assert len(rows) == 2
            # Both should have last values
            amtm_row = next(r for r in rows if r["symbol"] == "AMTM")
            j_row = next(r for r in rows if r["symbol"] == "J")
            assert amtm_row["price"] == "30.00"
            assert j_row["price"] == "126.00"

        finally:
            file1.unlink(missing_ok=True)
            file2.unlink(missing_ok=True)
            output.unlink(missing_ok=True)


class TestMergeSpinOffs:
    """Tests for merge_spin_offs function."""

    def test_merge_two_files(self):
        """Test merging two spin-offs files."""
        from schwab_csv_tools.merge_config_files import merge_spin_offs

        # Create first file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["dst", "src"])
            writer.writerow(["AMTM", "J"])
            file1 = Path(f1.name)

        # Create second file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f2:
            writer = csv.writer(f2)
            writer.writerow(["dst", "src"])
            writer.writerow(["XYZ", "ABC"])
            file2 = Path(f2.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_spin_offs([file1, file2], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have 2 rows
            assert len(rows) == 2

            # Check rows are sorted
            assert rows[0]["dst"] == "AMTM"
            assert rows[0]["src"] == "J"
            assert rows[1]["dst"] == "XYZ"
            assert rows[1]["src"] == "ABC"

        finally:
            file1.unlink(missing_ok=True)
            file2.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_deduplication_keeps_last(self):
        """Test that duplicates are deduplicated, keeping last occurrence."""
        from schwab_csv_tools.merge_config_files import merge_spin_offs

        # Create first file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["dst", "src"])
            writer.writerow(["AMTM", "J"])
            file1 = Path(f1.name)

        # Create second file with duplicate
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f2:
            writer = csv.writer(f2)
            writer.writerow(["dst", "src"])
            writer.writerow(["AMTM", "JACOBS"])
            file2 = Path(f2.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_spin_offs([file1, file2], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have only 1 row
            assert len(rows) == 1
            # Should keep last occurrence
            assert rows[0]["src"] == "JACOBS"

        finally:
            file1.unlink(missing_ok=True)
            file2.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_empty_files(self):
        """Test merging empty files."""
        from schwab_csv_tools.merge_config_files import merge_spin_offs

        # Create empty file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["dst", "src"])
            file1 = Path(f1.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_spin_offs([file1], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have no rows
            assert len(rows) == 0

        finally:
            file1.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_multiple_duplicates(self):
        """Test that multiple duplicates are all deduplicated."""
        from schwab_csv_tools.merge_config_files import merge_spin_offs

        # Create first file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["dst", "src"])
            writer.writerow(["AMTM", "J"])
            writer.writerow(["XYZ", "ABC"])
            file1 = Path(f1.name)

        # Create second file with duplicates
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f2:
            writer = csv.writer(f2)
            writer.writerow(["dst", "src"])
            writer.writerow(["AMTM", "JACOBS"])
            writer.writerow(["XYZ", "ABCD"])
            file2 = Path(f2.name)

        # Merge files
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_spin_offs([file1, file2], output, verbose=False)

            # Read merged output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have 2 rows
            assert len(rows) == 2
            # Both should have last values
            amtm_row = next(r for r in rows if r["dst"] == "AMTM")
            xyz_row = next(r for r in rows if r["dst"] == "XYZ")
            assert amtm_row["src"] == "JACOBS"
            assert xyz_row["src"] == "ABCD"

        finally:
            file1.unlink(missing_ok=True)
            file2.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def test_single_file(self):
        """Test processing a single file (no merging needed)."""
        from schwab_csv_tools.merge_config_files import merge_spin_offs

        # Create single file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f1:
            writer = csv.writer(f1)
            writer.writerow(["dst", "src"])
            writer.writerow(["AMTM", "J"])
            writer.writerow(["XYZ", "ABC"])
            file1 = Path(f1.name)

        # Process file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as out:
            output = Path(out.name)

        try:
            merge_spin_offs([file1], output, verbose=False)

            # Read output
            with open(output, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have 2 rows
            assert len(rows) == 2
            assert rows[0]["dst"] == "AMTM"
            assert rows[1]["dst"] == "XYZ"

        finally:
            file1.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
