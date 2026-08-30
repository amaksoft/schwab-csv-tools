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

    def test_load_mapping_warns_on_non_ticker_target(self, capsys):
        """Warn when a mapping points at a CUSIP or other non-ticker."""
        from schwab_csv_tools.postprocess import load_mapping_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Description,Symbol\n")
            f.write("VANGUARD S&P 500 UCITS ETF,G9T17W137\n")
            f.write("APPLE INC,AAPL\n")
            mapping_file = Path(f.name)

        try:
            mappings = load_mapping_file(mapping_file)
            # The mapping is still applied; this is a warning, not a rejection.
            assert mappings["vanguard s&p 500 ucits etf"] == "G9T17W137"
            out = capsys.readouterr().out
            assert "do not look like tickers" in out
            assert "G9T17W137" in out
            # The valid ticker is not reported.
            assert "AAPL" not in out
        finally:
            mapping_file.unlink()

    def test_load_mapping_silent_when_all_targets_are_tickers(self, capsys):
        """A mapping file of real tickers produces no warning."""
        from schwab_csv_tools.postprocess import load_mapping_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Description,Symbol\n")
            f.write("APPLE INC,AAPL\n")
            f.write("BERKSHIRE HATHAWAY B,BRK.B\n")
            mapping_file = Path(f.name)

        try:
            load_mapping_file(mapping_file)
            assert "do not look like tickers" not in capsys.readouterr().out
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


class TestSchwabDateParsing:
    """Test the shared Schwab date parser."""

    def test_plain_date(self):
        """A plain MM/DD/YYYY date is parsed as-is."""
        from datetime import datetime

        from schwab_csv_tools.common import parse_schwab_date

        assert parse_schwab_date("05/30/2025") == datetime(2025, 5, 30)

    def test_as_of_uses_the_settlement_date(self):
        """An "as of" row is dated by its leading (settlement) date.

        cgt-calc's Schwab parser uses the leading date, so the tax-year filter
        has to agree with it or a boundary row lands in the wrong year.
        """
        from datetime import datetime

        from schwab_csv_tools.common import parse_schwab_date

        assert parse_schwab_date("06/02/2025 as of 05/30/2025") == datetime(2025, 6, 2)

    def test_unparseable_date(self):
        """Junk and empty values return None."""
        from schwab_csv_tools.common import parse_schwab_date

        assert parse_schwab_date("") is None
        assert parse_schwab_date("not a date") is None


class TestSymbolRemapping:
    """Test rewriting symbols that disagree with the mapping file."""

    HEADERS = [
        "Date", "Action", "Symbol", "Description",
        "Price", "Quantity", "Fees & Comm", "Amount",
    ]

    def _write_input(self, rows):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writeheader()
            writer.writerows(rows)
            return Path(f.name)

    def _run(self, rows, remap_symbols):
        from schwab_csv_tools.postprocess import process_csv

        input_file = self._write_input(rows)
        output_file = input_file.parent / f"{input_file.stem}_out.csv"
        try:
            stats = process_csv(
                input_file,
                output_file,
                mapping={"unilever plc ftrades with due bills": "UL"},
                verbose=False,
                write_log=False,
                fix_rounding=False,
                remap_symbols=remap_symbols,
            )
            with output_file.open() as f:
                return stats, list(csv.DictReader(f))
        finally:
            input_file.unlink()
            if output_file.exists():
                output_file.unlink()

    def _row(self, symbol, description):
        return {
            "Date": "12/09/2025",
            "Action": "Reverse Split",
            "Symbol": symbol,
            "Description": description,
            "Price": "",
            "Quantity": "-185.0291",
            "Fees & Comm": "",
            "Amount": "",
        }

    def test_cusip_symbol_is_rewritten_to_the_ticker(self):
        """A CUSIP standing in for the ticker is replaced."""
        stats, rows = self._run(
            [self._row("904767704", "UNILEVER PLC FTRADES WITH DUE BILLS")],
            remap_symbols=True,
        )

        assert stats["remapped"] == 1
        assert rows[0]["Symbol"] == "UL"

    def test_matching_symbol_is_left_alone(self):
        """A row already under the mapped ticker is not counted as a change."""
        stats, rows = self._run(
            [self._row("UL", "UNILEVER PLC FTRADES WITH DUE BILLS")],
            remap_symbols=True,
        )

        assert stats["remapped"] == 0
        assert rows[0]["Symbol"] == "UL"

    def test_unmapped_description_is_left_alone(self):
        """Descriptions absent from the mapping file keep their symbol."""
        stats, rows = self._run(
            [self._row("912797QL4", "US TREASURY BILL DUE 08/26/25")],
            remap_symbols=True,
        )

        assert stats["remapped"] == 0
        assert rows[0]["Symbol"] == "912797QL4"

    def test_remapping_is_off_by_default(self):
        """Without the flag an existing symbol is never rewritten."""
        stats, rows = self._run(
            [self._row("904767704", "UNILEVER PLC FTRADES WITH DUE BILLS")],
            remap_symbols=False,
        )

        assert stats["remapped"] == 0
        assert rows[0]["Symbol"] == "904767704"


class TestTickerRecognition:
    """Test telling real tickers from Schwab's stand-in codes."""

    def test_real_tickers(self):
        """Short alphabetic symbols are tickers."""
        from schwab_csv_tools.common import looks_like_ticker

        for symbol in ["UL", "META", "VNGDF", "F"]:
            assert looks_like_ticker(symbol), symbol

    def test_codes_are_not_tickers(self):
        """CUSIPs, internal codes and generated acronyms are not tickers."""
        from schwab_csv_tools.common import looks_like_ticker

        for symbol in ["904767704", "G9T17W137", "912797QL4", "IEMWVFUE", ""]:
            assert not looks_like_ticker(symbol), symbol


class TestSymbolSplitDetection:
    """Test detection of one security booked under two symbols."""

    HEADERS = [
        "Date", "Action", "Symbol", "Description",
        "Price", "Quantity", "Fees & Comm", "Amount",
    ]

    def _row(self, symbol, description):
        return {
            "Date": "01/15/2025", "Action": "Buy", "Symbol": symbol,
            "Description": description, "Price": "$1.00", "Quantity": "1",
            "Fees & Comm": "", "Amount": "-$1.00",
        }

    def test_finds_description_under_two_symbols(self):
        """A description appearing under two symbols is reported."""
        from schwab_csv_tools.postprocess import detect_symbol_splits

        splits = detect_symbol_splits([
            self._row("UL", "UNILEVER PLC FTRADES WITH DUE BILLS"),
            self._row("904767704", "UNILEVER PLC FTRADES WITH DUE BILLS"),
            self._row("MSFT", "MICROSOFT CORP"),
        ])

        assert splits == {"UNILEVER PLC FTRADES WITH DUE BILLS": {"UL", "904767704"}}

    def test_consistent_symbols_are_not_reported(self):
        """One symbol per description is fine."""
        from schwab_csv_tools.postprocess import detect_symbol_splits

        assert detect_symbol_splits([
            self._row("MSFT", "MICROSOFT CORP"),
            self._row("MSFT", "MICROSOFT CORP"),
        ]) == {}

    def test_blank_symbols_are_ignored(self):
        """Rows still missing a symbol are not counted as a split."""
        from schwab_csv_tools.postprocess import detect_symbol_splits

        assert detect_symbol_splits([
            self._row("MSFT", "MICROSOFT CORP"),
            self._row("", "MICROSOFT CORP"),
        ]) == {}

    def test_ticker_plus_code_is_suspicious(self):
        """A ticker alongside a code is the one-security-two-ways signature."""
        from schwab_csv_tools.postprocess import split_is_suspicious

        assert split_is_suspicious({"UL", "904767704"})
        assert split_is_suspicious({"VNGDF", "G9T17W137"})

    def test_two_codes_are_not_suspicious(self):
        """Two CUSIPs sharing a generic description are different securities."""
        from schwab_csv_tools.postprocess import split_is_suspicious

        assert not split_is_suspicious({"912797QL4", "912797SR9"})

    def test_two_tickers_are_not_suspicious(self):
        """A ticker rename is handled by cgt-calc, not by remapping."""
        from schwab_csv_tools.postprocess import split_is_suspicious

        assert not split_is_suspicious({"FB", "META"})


class TestGeneratedSymbolCollisions:
    """Test that a synthetic symbol never lands on a real one."""

    HEADERS = [
        "Date", "Action", "Symbol", "Description",
        "Price", "Quantity", "Fees & Comm", "Amount",
    ]

    def test_generated_symbol_avoids_a_ticker_already_in_the_file(self, tmp_path):
        """A generated acronym must not collide with a held ticker.

        "UNILEVER LTD" acronyms to "UL". If the file already holds UL, a
        cash-in-lieu row taking that symbol would be deducted from the real
        UL pool, understating its allowable cost.
        """
        from schwab_csv_tools.postprocess import process_csv

        input_file = tmp_path / "in.csv"
        with input_file.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADERS)
            writer.writeheader()
            writer.writerow({
                "Date": "01/15/2025", "Action": "Buy", "Symbol": "UL",
                "Description": "UNILEVER PLC", "Price": "$50.00",
                "Quantity": "10", "Fees & Comm": "", "Amount": "-$500.00",
            })
            writer.writerow({
                "Date": "02/15/2025", "Action": "Cash In Lieu", "Symbol": "",
                "Description": "UNILEVER LTD", "Price": "",
                "Quantity": "", "Fees & Comm": "", "Amount": "$3.00",
            })
        output_file = tmp_path / "out.csv"

        process_csv(input_file, output_file, mapping={}, verbose=False,
                    write_log=False, fix_rounding=False)

        with output_file.open() as f:
            rows = list(csv.DictReader(f))

        assert rows[0]["Symbol"] == "UL"
        assert rows[1]["Symbol"] != "UL", "generated symbol collided with a real one"
        assert rows[1]["Symbol"].startswith("UL")
