# Schwab CSV Tools

Utilities for processing Charles Schwab CSV export files.

## Overview

This package provides command-line tools to help you manage and process Charles Schwab CSV exports:

- **cgt-calc-wrapper**: One-command workflow that merges, preprocesses, and runs cgt-calc
- **merge-schwab-csv**: Merge multiple transaction CSV files
- **merge-schwab-awards**: Merge multiple equity awards CSV files
- **merge-initial-prices**: Merge multiple initial_prices.csv files for cgt-calc
- **merge-spin-offs**: Merge multiple spin_offs.csv files for cgt-calc
- **postprocess-schwab-csv**: Fix missing symbols and rounding errors in transaction files

## Installation

### From PyPI (when published)

```bash
pip install schwab-csv-tools
```

### From source

```bash
git clone https://github.com/amaksoft/schwab-csv-tools.git
cd schwab-csv-tools
pip install -e .
```

## Command-Line Tools

### cgt-calc-wrapper

**The easiest way to get started** - runs the complete workflow in one command.

This wrapper orchestrates all the preprocessing steps and then runs `cgt-calc`:
1. Merges transaction CSV files
2. Merges equity awards CSV files
3. Merges initial prices files (if provided)
4. Merges spin-offs files (if provided)
5. Postprocesses transactions (fixes symbols and rounding errors)
6. Runs cgt-calc with the processed files

**Requirements:**
- `capital-gains-calculator` must be installed (`pip install capital-gains-calculator`)

**Usage:**

```bash
# Basic usage
cgt-calc-wrapper \
  --transactions tx1.csv tx2.csv \
  --awards awards1.csv awards2.csv \
  --year 2024

# With symbol mapping and PDF report
cgt-calc-wrapper \
  --transactions tx1.csv tx2.csv tx3.csv \
  --awards awards1.csv awards2.csv \
  --symbol-mapping my_mappings.csv \
  --year 2024 \
  --pdf report_2024.pdf

# With initial prices and spin-offs configuration
cgt-calc-wrapper \
  --transactions tx1.csv tx2.csv \
  --awards awards1.csv awards2.csv \
  --initial-prices prices1.csv prices2.csv \
  --spin-offs spinoffs.csv \
  --year 2024

# Keep intermediate files for inspection
cgt-calc-wrapper \
  --transactions tx.csv \
  --awards awards.csv \
  --year 2024 \
  --output-dir ./processed \
  --keep-intermediates

# Pass additional arguments to cgt-calc
cgt-calc-wrapper \
  --transactions tx.csv \
  --awards awards.csv \
  --year 2024 \
  -- --initial-prices initial.csv --verbose
```

**Options:**
- `-t, --transactions FILE [FILE ...]`: Transaction CSV files to merge (required)
- `-a, --awards FILE [FILE ...]`: Equity awards CSV files to merge (required)
- `-y, --year YEAR`: Tax year to calculate (required)
- `-i, --initial-prices FILE [FILE ...]`: Initial prices CSV files to merge (optional)
- `-s, --spin-offs FILE [FILE ...]`: Spin-offs CSV files to merge (optional)
- `-m, --symbol-mapping FILE`: CSV file mapping descriptions to symbols (optional)
- `--remap-symbols`: Also rewrite symbols that disagree with `--symbol-mapping`
- `-o, --output-dir DIR`: Directory for processed files (default: current directory)
- `-p, --pdf FILE`: Output PDF report path
- `--archive-in DIR [DIR ...]`: Read archives from earlier runs (read-only, see below)
- `--archive-out DIR`: Write this year's archive to DIR, for use as next year's `--archive-in`
- `--keep-intermediates`: Keep intermediate merged files (default: delete after processing)
- `-v, --verbose`: Show detailed processing information
- Additional arguments after `--` are passed directly to cgt-calc

**What it does:**
1. Creates `merged_transactions.csv` from your transaction files
2. Creates `merged_awards.csv` from your awards files
3. Creates `transactions_final.csv` with fixed symbols and rounding errors
4. Runs cgt-calc with the final files
5. Cleans up intermediate files (unless `--keep-intermediates` is used)

---

### Keeping history beyond Schwab's four-year limit

Schwab only exports the last four years of transactions. UK capital gains needs
the **whole** history, because the section 104 pool cost of anything you still
hold depends on when you first acquired it. Once a purchase or a vest scrolls
out of the export window, that cost basis is gone unless you kept it.

Archives are strictly one-way: a run **reads** `--archive-in` and **writes**
`--archive-out`, and the two may never be the same directory. Keep one
directory per tax year:

```bash
cgt-calc-wrapper \
  --transactions account1.csv account2.csv \
  --awards awards.csv \
  --year 2025 \
  --archive-in archive/2024 \
  --archive-out archive/2025 \
  --pdf tax_report_2025.pdf
```

Next year you pass `--archive-in archive/2025` and write `archive/2026`. The
archived files are added to the merge automatically, so there is nothing to
remember to include in `--transactions`, and deduplication means the archive
only ever contributes rows the new exports no longer reach.

**Why one-way.** Last year's archive is the only surviving copy of history that
Schwab will not export again. If a run could write to the directory it read
from, then a mistake in this year's inputs — one account's CSV missing, say —
would overwrite a complete archive with a shorter one and destroy that history
for good. Because the directories are disjoint, the worst a bad run can do is
produce a bad *new* archive, which you simply delete and re-run. The wrapper
refuses outright if `--archive-out` names an `--archive-in` directory.

To start from scratch, create the first `--archive-in` directory by hand with
whatever older history you have, named `transactions_archive_<year>.csv` and
`awards_archive_<year>.csv`.

**Archive the merge, not the postprocessed file.** `--archive-out` deliberately
writes the merged transactions from *before* postprocessing. The postprocessed
file has synthetic symbols substituted for blank ones (`SI00`, `WFD`, and so on,
which are position-dependent and not stable between runs) and rounding-corrected
amounts. Those rows no longer match the corresponding rows in a future Schwab
export byte for byte, so deduplication misses them and the overlapping history
gets counted twice.

Note the archive is the output of `merge-schwab-csv`, so matched
`Journaled Shares` and `Journal` pairs have already been removed from it. That
is what makes it a single-account view, but it also means a transfer whose
other leg only appears in a *later* export can never be paired up once the
first leg has aged out of Schwab's window. Keep the original broker exports as
well if that matters to you.

Archives written by older versions of this tool, which emitted oldest-first,
merge correctly too. Those files have their days ascending but each day's rows
still in Schwab's order, and the sort is stable, so re-sorting the days
restores the native layout.

---

### merge-schwab-csv

Merge multiple Schwab transaction CSV files into a single file.

**Features:**
- Deduplicates transactions (by date, symbol, action, quantity, price)
- Sorts by date, **newest first**, matching Schwab's own export order
- Validates CSV format
- Handles both 8-column and 9-column Schwab formats

**Why newest-first matters:** `cgt-calc`'s Schwab parser assumes a newest-first
list. It matches paired rows (Cancel Buy/Buy, Cash Merger/Adj, Full
Redemption/Adj, Reverse Split) in that orientation and then reverses the whole
list to get chronological order. Emitting oldest-first would both break that
pair matching and invert the order of same-day transactions in the final
calculation. The sort is stable, so within one date each input file's original
row order is preserved.

**Usage:**

```bash
# Merge two files
merge-schwab-csv file1.csv file2.csv

# Specify output file
merge-schwab-csv -o merged.csv file1.csv file2.csv file3.csv

# Verbose mode
merge-schwab-csv -v file1.csv file2.csv
```

**Options:**
- `-o, --output FILE`: Output path (default: `merged_schwab_YYYYMMDD_HHMMSS.csv`)
- `-v, --verbose`: Show detailed processing information

---

### merge-schwab-awards

Merge multiple Schwab equity awards CSV files into a single file.

**Features:**
- Handles 2-row paired format (each award spans 2 CSV rows)
- Deduplicates full 2-row award pairs
- Sorts by award date
- Supports multiple date formats (MM/DD/YYYY and YYYY/MM/DD)

**Usage:**

```bash
# Merge award files
merge-schwab-awards awards1.csv awards2.csv

# Specify output file
merge-schwab-awards -o merged_awards.csv awards1.csv awards2.csv

# Verbose mode
merge-schwab-awards -v awards1.csv awards2.csv
```

**Options:**
- `-o, --output FILE`: Output path (default: `merged_schwab_awards_YYYYMMDD_HHMMSS.csv`)
- `-v, --verbose`: Show detailed processing information

---

### merge-initial-prices

Merge multiple initial_prices.csv files for use with cgt-calc.

**Features:**
- Deduplicates by (date, symbol) - keeps last occurrence
- Sorts output by date and symbol
- Skips `#` comment lines and blank lines
- Compatible with cgt-calc's `--initial-prices-file` option

**Usage:**

```bash
# Merge two initial prices files
merge-initial-prices prices1.csv prices2.csv -o merged_prices.csv

# Verbose mode shows duplicates
merge-initial-prices -v prices1.csv prices2.csv -o merged.csv
```

**File Format:**
```csv
date,symbol,price
"May 30, 2025",AMTM,29.72
"May 30, 2025",J,125.72
```

**Options:**
- `-o, --output FILE`: Output path (required)
- `-v, --verbose`: Show detailed processing information including duplicates

---

### merge-spin-offs

Merge multiple spin_offs.csv files for use with cgt-calc.

**Features:**
- Deduplicates by destination ticker - keeps last occurrence
- Sorts output by destination ticker
- Skips `#` comment lines and blank lines, so a file carrying a provenance
  banner such as `# Last updated: 2025-12-27` still parses
- Compatible with cgt-calc's `--spin-offs-file` option

**Usage:**

```bash
# Merge spin-offs files
merge-spin-offs spinoffs1.csv spinoffs2.csv -o merged_spinoffs.csv

# Verbose mode shows which mappings are replaced
merge-spin-offs -v spinoffs1.csv spinoffs2.csv -o merged.csv
```

**File Format:**
```csv
dst,src
AMTM,J
```

**Options:**
- `-o, --output FILE`: Output path (required)
- `-v, --verbose`: Show detailed processing information including duplicates

---

### postprocess-schwab-csv

Fix common issues in Schwab transaction CSV files.

**Features:**
- **Symbol fixing**: Add missing symbols using mapping file or generate synthetic symbols
- **Symbol remapping**: Rewrite symbols that are present but wrong (`--remap-symbols`)
- **Rounding error fix**: Detect and fix small discrepancies in dividend reinvestment amounts
- Transparent change logging

**Usage:**

```bash
# Fix missing symbols with auto-generation
postprocess-schwab-csv transactions.csv

# Use mapping file for known securities
postprocess-schwab-csv transactions.csv -m symbol_mappings.csv

# Fix rounding errors
postprocess-schwab-csv transactions.csv --fix-rounding

# Combined with output path and logging
postprocess-schwab-csv transactions.csv -m mappings.csv -o fixed.csv --write-log

# Both fixes together
postprocess-schwab-csv transactions.csv -m mappings.csv --fix-rounding
```

**Options:**
- `-m, --mapping FILE`: CSV file mapping descriptions to symbols
- `-o, --output FILE`: Output path (default: `INPUT_processed.csv`)
- `-v, --verbose`: Show detailed processing information
- `--write-log`: Write change log to `INPUT_symbol_changes.log`
- `--fix-rounding`: Fix small rounding errors in dividend reinvestment amounts
- `--tax-year YEAR`: Drop transactions after April 5, YEAR+1
- `--remap-symbols`: Also rewrite symbols that are present but disagree with the mapping file

**Symbol Remapping:**

By default only *missing* symbols are filled in. With `--remap-symbols`, a row
whose description appears in the mapping file is rewritten to the mapped symbol
even if it already has one. This is for the case where Schwab books the same
security under two different identifiers, which would otherwise split one
holding into two unrelated pools. For example, an ADR trading with due bills
around a corporate action:

```csv
Description,Symbol
UNILEVER PLC FTRADES WITH DUE BILLS,UL
```

Rows carrying the CUSIP `904767704` under that description are moved to `UL`,
joining the rest of the position.

**Symbol Mapping File Format:**

Create a CSV file with two columns:

```csv
Description,Symbol
ISHARES EDGE MSCI WORLD VALUE FACTOR UCIT ETF GB SHRS,IEMWVF
VANGUARD FTSE ALL WORLD,VWRL
```

- Case-insensitive matching
- Exact description match required

**Synthetic Symbol Generation:**

When no mapping is provided, symbols are generated as acronyms from descriptions:

- `ISHARES EDGE MSCI WORLD VALUE FACTOR` → `IEMWVF`
- `VANGUARD S&P 500 ETF` → `VSE`
- `US TREASURY NOTE 4.25%` → `UTN`

**Rounding Error Fix:**

Detects and fixes small discrepancies ($0.01-$1.00) in dividend reinvestment transactions where the amount doesn't exactly match quantity × price.

## Workflow Examples

### Quick Start (Recommended)

Use the wrapper to run everything in one command:

```bash
cgt-calc-wrapper \
  --transactions account1_2023.csv account1_2024.csv account2_2023.csv account2_2024.csv \
  --awards awards_2023.csv awards_2024.csv \
  --initial-prices prices.csv \
  --spin-offs spinoffs.csv \
  --symbol-mapping my_mappings.csv \
  --year 2024 \
  --pdf tax_report_2024.pdf
```

### Manual Step-by-Step

For more control over the process, run each step individually:

```bash
# 1. Merge all transaction files
merge-schwab-csv -o all_transactions.csv \
  account1_2023.csv \
  account1_2024.csv \
  account2_2023.csv \
  account2_2024.csv

# 2. Merge all equity award files
merge-schwab-awards -o all_awards.csv \
  awards_2023.csv \
  awards_2024.csv

# 3. (Optional) Merge initial prices files
merge-initial-prices -o all_initial_prices.csv \
  prices1.csv \
  prices2.csv

# 4. (Optional) Merge spin-offs files
merge-spin-offs -o all_spinoffs.csv \
  spinoffs1.csv \
  spinoffs2.csv

# 5. Fix missing symbols and rounding errors
postprocess-schwab-csv all_transactions.csv \
  -m my_symbol_mappings.csv \
  --fix-rounding \
  -o transactions_final.csv

# 6. Run cgt-calc
cgt-calc \
  --schwab transactions_final.csv \
  --schwab-awards all_awards.csv \
  --initial-prices-file all_initial_prices.csv \
  --spin-offs-file all_spinoffs.csv \
  --year 2024 \
  --output tax_report_2024.pdf
```

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/amaksoft/schwab-csv-tools.git
cd schwab-csv-tools

# Install in development mode
pip install -e .

# Run tests
pytest

# Run tests with verbose output
pytest -v
```

### Project Structure

```
schwab_csv_tools/
├── schwab_csv_tools/
│   ├── __init__.py
│   ├── common.py              # Shared utilities, constants, dataclasses
│   ├── cgt_wrapper.py          # One-command workflow orchestrator
│   ├── merge_transactions.py   # Transaction CSV merging
│   ├── merge_awards.py         # Equity awards CSV merging
│   ├── merge_config_files.py   # Initial prices and spin-offs merging
│   └── postprocess.py          # Symbol fixing and rounding errors
├── tests/
│   ├── test_merge_transactions.py
│   ├── test_merge_awards.py
│   ├── test_merge_config_files.py
│   └── test_postprocess_schwab_csv.py
├── pyproject.toml
├── README.md
└── LICENSE
```

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Related Projects

- [capital-gains-calculator](https://github.com/KapJI/capital-gains-calculator) - UK capital gains tax calculator that works with Schwab exports

## Support

If you encounter any issues or have questions, please file an issue on GitHub.
