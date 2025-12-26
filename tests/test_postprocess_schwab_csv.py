"""Test postprocess_schwab_csv.py script."""

import csv
import tempfile
from pathlib import Path


class TestSymbolGeneration:
    """Test synthetic symbol generation algorithm."""

    def test_generate_symbol_basic(self):
        """Test basic acronym generation."""
        from schwab_csv_tools.postprocess import generate_symbol_from_description

        assert generate_symbol_from_description("ISHARES EDGE MSCI WORLD VALUE FACTOR") == "IEMWVF"
        assert generate_symbol_from_description("VANGUARD S&P 500 ETF") == "VSP5E"  # & removed, 500 becomes 5
        assert generate_symbol_from_description("US TREASURY NOTE") == "UTN"

    def test_generate_symbol_empty(self):
        """Test empty description."""
        from schwab_csv_tools.postprocess import generate_symbol_from_description

        assert generate_symbol_from_description("") == "UNKNOWN"
        assert generate_symbol_from_description("   ") == "UNKNOWN"

    def test_generate_symbol_special_chars(self):
        """Test handling of special characters."""
        from schwab_csv_tools.postprocess import generate_symbol_from_description

        assert generate_symbol_from_description("AT&T INC") == "ATI"  # & becomes space, so AT T INC
        assert generate_symbol_from_description("JOHNSON & JOHNSON") == "JJ"
        assert generate_symbol_from_description("3M COMPANY (MMM)") == "3CM"  # Numbers kept, () removed

    def test_generate_symbol_truncation(self):
        """Test truncation to 8 characters."""
        from schwab_csv_tools.postprocess import generate_symbol_from_description

        long_desc = "FIRST SECOND THIRD FOURTH FIFTH SIXTH SEVENTH EIGHTH NINTH TENTH"
        result = generate_symbol_from_description(long_desc)
        assert len(result) <= 8
        assert result == "FSTFFSSE"  # First 8 letters

    def test_generate_symbol_lowercase(self):
        """Test case normalization."""
        from schwab_csv_tools.postprocess import generate_symbol_from_description

        assert generate_symbol_from_description("apple inc") == "AI"
        assert generate_symbol_from_description("Apple Inc") == "AI"
        assert generate_symbol_from_description("APPLE INC") == "AI"


class TestMappingFile:
    """Test mapping file loading."""

    def test_load_valid_mapping_file(self):
        """Test loading valid mapping file."""
        from schwab_csv_tools.postprocess import load_mapping_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Description,Symbol\n")
            f.write("ISHARES EDGE MSCI WORLD,IWVF\n")
            f.write("VANGUARD FTSE ALL WORLD,VWRL\n")
            mapping_file = Path(f.name)

        try:
            mappings = load_mapping_file(mapping_file)
            assert len(mappings) == 2
            assert mappings["ishares edge msci world"] == "IWVF"
            assert mappings["vanguard ftse all world"] == "VWRL"
        finally:
            mapping_file.unlink()

    def test_load_mapping_case_insensitive(self):
        """Test case-insensitive matching."""
        from schwab_csv_tools.postprocess import load_mapping_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Description,Symbol\n")
            f.write("Apple Inc,AAPL\n")
            mapping_file = Path(f.name)

        try:
            mappings = load_mapping_file(mapping_file)
            assert mappings["apple inc"] == "AAPL"
            assert mappings.get("APPLE INC") is None  # Keys are lowercased
        finally:
            mapping_file.unlink()

    def test_load_mapping_duplicates(self):
        """Test duplicate description handling (last wins)."""
        from schwab_csv_tools.postprocess import load_mapping_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Description,Symbol\n")
            f.write("APPLE INC,AAPL1\n")
            f.write("APPLE INC,AAPL2\n")
            mapping_file = Path(f.name)

        try:
            mappings = load_mapping_file(mapping_file)
            assert mappings["apple inc"] == "AAPL2"  # Last entry wins
        finally:
            mapping_file.unlink()


class TestRoundingFix:
    """Test rounding error fix functionality."""

    def test_fix_dividend_reinvestment_rounding(self):
        """Test fixing dividend reinvestment rounding errors."""
        from schwab_csv_tools.postprocess import process_csv

        # Create test CSV with rounding error
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writeheader()
            # Actual: 0.571 * 54.34 = 31.03014, but CSV shows $31.04
            writer.writerow({
                "Date": "01/15/2024",
                "Action": "Reinvest Dividend",
                "Symbol": "MSFT",
                "Description": "MICROSOFT CORP",
                "Price": "$54.34",
                "Quantity": "0.571",
                "Fees & Comm": "",
                "Amount": "-$31.04",
            })
            input_file = Path(f.name)

        output_file = input_file.parent / f"{input_file.stem}_output.csv"

        try:
            stats = process_csv(
                input_file,
                output_file,
                mapping={},
                verbose=False,
                write_log=False,
                fix_rounding=True,
            )

            assert stats["rounding_fixed"] == 1

            # Read output and verify fix
            with output_file.open() as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]["Amount"] == "-$31.03"  # Fixed from $31.04

        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()

    def test_no_fix_with_fees(self):
        """Test that transactions with fees are handled correctly."""
        from schwab_csv_tools.postprocess import process_csv

        # Create test CSV with fees
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writeheader()
            # 160 * 489.55 - 0.66 = 78327.34 (correct with fees)
            writer.writerow({
                "Date": "01/15/2024",
                "Action": "Sell",
                "Symbol": "META",
                "Description": "META PLATFORMS INC",
                "Price": "$489.55",
                "Quantity": "160",
                "Fees & Comm": "$0.66",
                "Amount": "$78327.34",
            })
            input_file = Path(f.name)

        output_file = input_file.parent / f"{input_file.stem}_output.csv"

        try:
            stats = process_csv(
                input_file,
                output_file,
                mapping={},
                verbose=False,
                write_log=False,
                fix_rounding=True,
            )

            assert stats["rounding_fixed"] == 0  # No rounding fix needed

        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()

    def test_ignores_large_differences(self):
        """Test that large differences (bonds) are ignored."""
        from schwab_csv_tools.postprocess import process_csv

        # Create test CSV with bond pricing
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writeheader()
            # Bond with per-$100 pricing - large difference is expected
            writer.writerow({
                "Date": "01/15/2024",
                "Action": "Buy",
                "Symbol": "91282CMF5",
                "Description": "US TREASURY NOTE",
                "Price": "$9917.27",
                "Quantity": "40000",
                "Fees & Comm": "",
                "Amount": "-$3987500.00",
            })
            input_file = Path(f.name)

        output_file = input_file.parent / f"{input_file.stem}_output.csv"

        try:
            stats = process_csv(
                input_file,
                output_file,
                mapping={},
                verbose=False,
                write_log=False,
                fix_rounding=True,
            )

            assert stats["rounding_fixed"] == 0  # Ignored (diff > $1.00)

        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()


class TestSymbolFixing:
    """Test symbol fixing functionality."""

    def test_fix_missing_symbols_with_mapping(self):
        """Test fixing missing symbols using mapping file."""
        from schwab_csv_tools.postprocess import process_csv

        # Create test CSV with missing symbols
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writeheader()
            writer.writerow({
                "Date": "01/15/2024",
                "Action": "Buy",  # Security action
                "Symbol": "",  # Missing
                "Description": "ISHARES EDGE MSCI WORLD",
                "Price": "$100.00",
                "Quantity": "10",
                "Fees & Comm": "$1.00",
                "Amount": "-$1,001.00",
            })
            input_file = Path(f.name)

        output_file = input_file.parent / f"{input_file.stem}_output.csv"
        mapping = {"ishares edge msci world": "IEMW"}

        try:
            stats = process_csv(
                input_file,
                output_file,
                mapping=mapping,
                verbose=False,
                write_log=False,
                fix_rounding=False,
            )

            assert stats["missing_symbols"] == 1
            assert stats["mapped"] == 1
            assert stats["generated"] == 0

            # Read output and verify
            with output_file.open() as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert rows[0]["Symbol"] == "IEMW"

        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()

    def test_fix_missing_symbols_generated(self):
        """Test fixing missing symbols with synthetic generation."""
        from schwab_csv_tools.postprocess import process_csv

        # Create test CSV with missing symbols
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Date", "Action", "Symbol", "Description",
                "Price", "Quantity", "Fees & Comm", "Amount"
            ])
            writer.writeheader()
            writer.writerow({
                "Date": "01/15/2024",
                "Action": "Sell",  # Security action
                "Symbol": "",  # Missing
                "Description": "APPLE INC",
                "Price": "$150.00",
                "Quantity": "10",
                "Fees & Comm": "$1.00",
                "Amount": "$1,499.00",
            })
            input_file = Path(f.name)

        output_file = input_file.parent / f"{input_file.stem}_output.csv"

        try:
            stats = process_csv(
                input_file,
                output_file,
                mapping={},
                verbose=False,
                write_log=False,
                fix_rounding=False,
            )

            assert stats["missing_symbols"] == 1
            assert stats["mapped"] == 0
            assert stats["generated"] == 1

            # Read output and verify
            with output_file.open() as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert rows[0]["Symbol"] == "AI"  # Generated from "APPLE INC"

        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()
