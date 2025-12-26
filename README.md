# Schwab CSV Tools

Utilities for processing Charles Schwab CSV export files.

## Overview

This package provides command-line tools to help you manage and process Charles Schwab CSV exports:

- **cgt-calc-wrapper**: One-command workflow that merges, preprocesses, and runs cgt-calc
- **merge-schwab-csv**: Merge multiple transaction CSV files
- **merge-schwab-awards**: Merge multiple equity awards CSV files
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
3. Postprocesses transactions (fixes symbols and rounding errors)
4. Runs cgt-calc with the processed files

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
- `-m, --symbol-mapping FILE`: CSV file mapping descriptions to symbols (optional)
- `-o, --output-dir DIR`: Directory for processed files (default: current directory)
- `-p, --pdf FILE`: Output PDF report path
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

### merge-schwab-csv

Merge multiple Schwab transaction CSV files into a single file.

**Features:**
- Deduplicates transactions (by date, symbol, action, quantity, price)
- Sorts by date (oldest first)
- Validates CSV format
- Handles both 8-column and 9-column Schwab formats

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

### postprocess-schwab-csv

Fix common issues in Schwab transaction CSV files.

**Features:**
- **Symbol fixing**: Add missing symbols using mapping file or generate synthetic symbols
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

# 3. Fix missing symbols and rounding errors
postprocess-schwab-csv all_transactions.csv \
  -m my_symbol_mappings.csv \
  --fix-rounding \
  -o transactions_final.csv

# 4. Run cgt-calc
cgt-calc \
  --schwab transactions_final.csv \
  --schwab-awards all_awards.csv \
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
│   └── postprocess.py          # Symbol fixing and rounding errors
├── tests/
│   ├── test_merge_transactions.py
│   ├── test_merge_awards.py
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
