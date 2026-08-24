#!/usr/bin/env python3
"""Wrapper script to run Schwab CSV preprocessing and cgt-calc in one command.

This script orchestrates the complete workflow:
1. Merge transaction CSV files
2. Merge equity awards CSV files
3. Postprocess transactions (fix symbols and rounding errors)
4. Run cgt-calc with the processed files
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .merge_config_files import merge_initial_prices, merge_spin_offs


def _find_executable_in_env(script_name: str) -> Path | None:
    """Find an executable in the same Python environment.

    Searches in the following order:
    1. In the same directory as the Python executable (Scripts/bin folder)
    2. On Windows, check Scripts directory with .exe extension
    3. In the user site-packages bin directory (for --user installs)
    4. In PATH using shutil.which()

    Args:
        script_name: Name of the executable to find

    Returns:
        Path to the executable if found, None otherwise
    """
    python_exe = Path(sys.executable)
    bin_dir = python_exe.parent

    # Check in the same directory as Python
    candidate = bin_dir / script_name
    if candidate.exists() and candidate.is_file():
        return candidate

    # On Windows, might be in Scripts directory with .exe extension
    if bin_dir.name == "Scripts":
        candidate_exe = bin_dir / f"{script_name}.exe"
        if candidate_exe.exists() and candidate_exe.is_file():
            return candidate_exe

    # Check user site-packages bin directory (for --user installs)
    # This is typically ~/Library/Python/X.Y/bin on macOS, ~/.local/bin on Linux
    try:
        import site

        user_base = site.getuserbase()
        if user_base:
            user_bin = Path(user_base) / "bin" / script_name
            if user_bin.exists() and user_bin.is_file():
                return user_bin
    except (ImportError, AttributeError):
        pass

    # Fall back to searching PATH
    path_result = shutil.which(script_name)
    return Path(path_result) if path_result else None


def find_script_in_same_env(script_name: str) -> str:
    """Find a script in the same Python environment.

    Returns the full path if found, otherwise returns just the script name
    (which will rely on PATH).

    Args:
        script_name: Name of the script to find

    Returns:
        Full path to script or just script name as fallback
    """
    result = _find_executable_in_env(script_name)
    return str(result) if result else script_name


def find_cgt_calc() -> Path | None:
    """Find cgt-calc executable in the same Python environment.

    Returns:
        Path to cgt-calc executable or None if not found
    """
    return _find_executable_in_env("cgt-calc")


TRANSACTIONS_ARCHIVE_GLOB = "transactions_archive_*.csv"
AWARDS_ARCHIVE_GLOB = "awards_archive_*.csv"


def collect_archive_inputs(directories: list[str]) -> tuple[list[str], list[str]]:
    """Find archived transaction and awards files in the given directories.

    Args:
        directories: Directories holding archives written by earlier runs

    Returns:
        Tuple of (transaction files, awards files), each sorted

    Raises:
        SystemExit: If a directory does not exist or holds no archive files
    """
    transactions: list[str] = []
    awards: list[str] = []

    for directory in directories:
        path = Path(directory)
        if not path.is_dir():
            print(f"\n❌ Error: --archive-in directory not found: {path}")
            sys.exit(1)

        found_transactions = sorted(path.glob(TRANSACTIONS_ARCHIVE_GLOB))
        found_awards = sorted(path.glob(AWARDS_ARCHIVE_GLOB))
        if not found_transactions and not found_awards:
            print(
                f"\n❌ Error: no archive files in {path}. Expected files named "
                f"{TRANSACTIONS_ARCHIVE_GLOB} or {AWARDS_ARCHIVE_GLOB}."
            )
            sys.exit(1)

        transactions += [str(p) for p in found_transactions]
        awards += [str(p) for p in found_awards]

    return transactions, awards


def check_archive_dirs_are_separate(archive_in: list[str], archive_out: str) -> None:
    """Refuse to write an archive into a directory being read as input.

    Reading and writing the same archive is what made earlier versions of this
    tool able to damage history: a run with a missing input could overwrite a
    complete archive with a shorter one. Keeping the two directories disjoint
    makes last year's archive immutable by construction.

    Raises:
        SystemExit: If the output directory is also an input directory
    """
    out = Path(archive_out).resolve()
    for directory in archive_in:
        if Path(directory).resolve() == out:
            print(
                f"\n❌ Error: --archive-out {archive_out} is also an --archive-in "
                "directory."
            )
            print(
                "   Archives are read-only inputs. Write this year's archive to a "
                "new directory, and pass it as --archive-in next year."
            )
            sys.exit(1)


def run_command(cmd: list[str], description: str) -> None:
    """Run a command and handle errors.

    Checks both exit code and stderr for error indicators.
    Stdout is streamed in real-time, stderr is captured for error detection.
    Interactive prompts will fail immediately since stdin is set to DEVNULL.
    """
    print(f"\n{'=' * 70}")
    print(f"{description}")
    print(f"{'=' * 70}")
    print(f"$ {' '.join(cmd)}\n")

    result = subprocess.run(
        cmd,
        check=False,
        stdin=subprocess.DEVNULL,  # Fail immediately on interactive prompts
        stderr=subprocess.PIPE,  # Capture stderr for error detection
        text=True
    )

    # Check stderr for critical errors (cgt-calc returns 0 even on errors)
    has_critical_error = False
    if result.stderr:
        # Print stderr to user
        print(result.stderr, end='', file=sys.stderr)
        # Check for error indicators
        has_critical_error = (
            'CRITICAL:' in result.stderr or 'Traceback' in result.stderr
        )

    if result.returncode != 0:
        print(f"\n❌ Error: {description} failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    elif has_critical_error:
        print(f"\n❌ Error: {description} failed (critical error detected)")
        sys.exit(1)

    print(f"\n✅ {description} completed successfully")


def main() -> None:
    """Main entry point for the CGT wrapper."""
    parser = argparse.ArgumentParser(
        description="Run Schwab CSV preprocessing and cgt-calc in one command",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  # Basic usage with required files
  cgt-calc-wrapper \\
    --transactions tx1.csv tx2.csv \\
    --awards awards1.csv awards2.csv \\
    --year 2024

  # With optional config files
  cgt-calc-wrapper \\
    --transactions tx1.csv tx2.csv \\
    --awards awards1.csv awards2.csv \\
    --initial-prices prices.csv \\
    --spin-offs spinoffs.csv \\
    --year 2024

  # With all optional settings
  cgt-calc-wrapper \\
    --transactions tx1.csv tx2.csv \\
    --awards awards1.csv awards2.csv \\
    --initial-prices prices1.csv prices2.csv \\
    --spin-offs spinoffs.csv \\
    --symbol-mapping mappings.csv \\
    --output-dir ./processed \\
    --year 2024 \\
    --pdf output.pdf

  # Pass additional cgt-calc arguments
  cgt-calc-wrapper \\
    --transactions tx.csv \\
    --awards awards.csv \\
    --year 2024 \\
    -- --verbose
        """,
    )

    # Input files
    parser.add_argument(
        "--transactions",
        "-t",
        nargs="+",
        required=True,
        metavar="FILE",
        help="Schwab transaction CSV files to merge",
    )
    parser.add_argument(
        "--awards",
        "-a",
        nargs="+",
        required=True,
        metavar="FILE",
        help="Schwab equity awards CSV files to merge",
    )
    parser.add_argument(
        "--initial-prices",
        "-i",
        nargs="+",
        metavar="FILE",
        help="Initial prices CSV files to merge (optional)",
    )
    parser.add_argument(
        "--spin-offs",
        "-s",
        nargs="+",
        metavar="FILE",
        help="Spin-offs CSV files to merge (optional)",
    )

    # Processing options
    parser.add_argument(
        "--symbol-mapping",
        "-m",
        metavar="FILE",
        help="CSV file mapping descriptions to symbols (optional)",
    )
    parser.add_argument(
        "--remap-symbols",
        action="store_true",
        help=(
            "also rewrite symbols that disagree with --symbol-mapping "
            "(e.g. a CUSIP used instead of the ticker)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        metavar="DIR",
        default=".",
        help="Directory for intermediate processed files (default: current directory)",
    )
    parser.add_argument(
        "--archive-in",
        nargs="+",
        metavar="DIR",
        help=(
            "directories holding archives written by earlier runs. Their "
            "transaction and awards files are added to the merge, carrying "
            "history that has aged out of Schwab's four-year export window. "
            "Read-only: nothing in these directories is ever written to"
        ),
    )
    parser.add_argument(
        "--archive-out",
        metavar="DIR",
        help=(
            "directory to write this year's archive to, for use as --archive-in "
            "next year. Must not be an --archive-in directory. The archive holds "
            "the merged rows before symbol and rounding fixes, so that it still "
            "deduplicates against future Schwab exports; matched inter-account "
            "transfers are already filtered out of it"
        ),
    )
    parser.add_argument(
        "--keep-intermediates",
        nargs="?",
        const="finals",
        default=None,
        metavar="A",
        help="Keep intermediate files: no value = keep finals only, 'A' = keep all (default: delete all)",
    )

    # CGT-calc options
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        required=True,
        help="Tax year to calculate (required for cgt-calc)",
    )
    parser.add_argument(
        "--pdf",
        "-p",
        metavar="FILE",
        help="Output PDF report path (passed to cgt-calc as --output)",
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed processing information",
    )

    # Additional cgt-calc arguments
    parser.add_argument(
        "cgt_calc_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments to pass to cgt-calc (after --)",
    )

    args = parser.parse_args()

    # Validate cgt-calc is installed
    cgt_calc = find_cgt_calc()
    if not cgt_calc:
        print("❌ Error: cgt-calc not found in PATH")
        print("Please install: pip install capital-gains-calculator")
        sys.exit(1)

    # Resolve archive inputs before anything is written. Archives are strictly
    # read-only here; this year's goes to a separate --archive-out directory.
    transaction_files = list(args.transactions)
    awards_files = list(args.awards)
    if args.archive_in:
        if args.archive_out:
            check_archive_dirs_are_separate(args.archive_in, args.archive_out)
        archived_transactions, archived_awards = collect_archive_inputs(
            args.archive_in
        )
        # Appended after the fresh exports so that, where both hold a row, the
        # export's copy is the one kept and sets the same-day ordering.
        transaction_files += archived_transactions
        awards_files += archived_awards
        print(
            f"Using {len(archived_transactions)} archived transaction file(s) and "
            f"{len(archived_awards)} archived awards file(s)"
        )

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Define intermediate file paths
    transactions_raw_merged = output_dir / f"transactions_raw_merged_{args.year}.csv"
    awards_merged = output_dir / f"awards_merged_{args.year}.csv"
    transactions_merged = output_dir / f"transactions_merged_{args.year}.csv"
    initial_prices_merged = (
        output_dir / f"initial_prices_merged_{args.year}.csv"
        if args.initial_prices
        else None
    )
    spin_offs_merged = (
        output_dir / f"spin_offs_merged_{args.year}.csv"
        if args.spin_offs
        else None
    )

    try:
        step_num = 1
        total_steps = 4
        if args.initial_prices:
            total_steps += 1
        if args.spin_offs:
            total_steps += 1

        # Step 1: Merge transaction files
        merge_tx_cmd = [
            find_script_in_same_env("merge-schwab-csv"),
            "-o",
            str(transactions_raw_merged),
            *transaction_files,
        ]
        if args.verbose:
            merge_tx_cmd.append("-v")
        run_command(
            merge_tx_cmd, f"Step {step_num}/{total_steps}: Merging transaction files"
        )
        step_num += 1

        # Step 2: Merge equity awards files
        merge_awards_cmd = [
            find_script_in_same_env("merge-schwab-awards"),
            "-o",
            str(awards_merged),
            *awards_files,
        ]
        if args.verbose:
            merge_awards_cmd.append("-v")
        run_command(
            merge_awards_cmd,
            f"Step {step_num}/{total_steps}: Merging equity awards files",
        )
        step_num += 1

        # Archive as soon as the merges are done. cgt-calc failing is a routine
        # outcome, and the archive is the one output that must survive it: it
        # holds history that Schwab will no longer export.
        if args.archive_out:
            archive_dir = Path(args.archive_out)
            archive_dir.mkdir(parents=True, exist_ok=True)
            transactions_archive = archive_dir / f"transactions_archive_{args.year}.csv"
            awards_archive = archive_dir / f"awards_archive_{args.year}.csv"
            shutil.copyfile(transactions_raw_merged, transactions_archive)
            shutil.copyfile(awards_merged, awards_archive)
            print("\n📦 Archived merged history for future runs:")
            print(f"   {transactions_archive}")
            print(f"   {awards_archive}")
            print(
                f"   Pass --archive-in {archive_dir} to next year's run so history "
                "older than Schwab's four-year export window is not lost."
            )

        # Step 3 (optional): Merge initial prices files
        if args.initial_prices:
            if args.verbose:
                print(f"\n{'=' * 70}")
                print(f"Step {step_num}/{total_steps}: Merging initial prices files")
                print(f"{'=' * 70}\n")
            merge_initial_prices(
                [Path(f) for f in args.initial_prices],
                initial_prices_merged,
                args.verbose,
            )
            print(f"\n✅ Step {step_num}/{total_steps} completed successfully")
            step_num += 1

        # Step 4 (optional): Merge spin-offs files
        if args.spin_offs:
            if args.verbose:
                print(f"\n{'=' * 70}")
                print(f"Step {step_num}/{total_steps}: Merging spin-offs files")
                print(f"{'=' * 70}\n")
            merge_spin_offs(
                [Path(f) for f in args.spin_offs], spin_offs_merged, args.verbose
            )
            print(f"\n✅ Step {step_num}/{total_steps} completed successfully")
            step_num += 1

        # Step N-1: Postprocess transactions
        postprocess_cmd = [
            find_script_in_same_env("postprocess-schwab-csv"),
            str(transactions_raw_merged),
            "-o",
            str(transactions_merged),
            "--fix-rounding",
            "--tax-year",
            str(args.year),
        ]
        if args.symbol_mapping:
            postprocess_cmd.extend(["-m", args.symbol_mapping])
            if args.remap_symbols:
                postprocess_cmd.append("--remap-symbols")
        if args.verbose:
            postprocess_cmd.append("-v")
        run_command(
            postprocess_cmd, f"Step {step_num}/{total_steps}: Postprocessing transactions"
        )
        step_num += 1

        # Step N: Run cgt-calc
        cgt_calc_cmd = [
            str(cgt_calc),
            "--schwab-file",
            str(transactions_merged),
            "--schwab-award-file",
            str(awards_merged),
            "--year",
            str(args.year),
        ]

        # Add initial prices if provided
        if initial_prices_merged:
            cgt_calc_cmd.extend(["--initial-prices-file", str(initial_prices_merged)])

        # Add spin-offs if provided
        if spin_offs_merged:
            cgt_calc_cmd.extend(["--spin-offs-file", str(spin_offs_merged)])

        if args.pdf:
            cgt_calc_cmd.extend(["--output", args.pdf])

        # Add any additional arguments (after --)
        if args.cgt_calc_args and args.cgt_calc_args[0] == "--":
            cgt_calc_cmd.extend(args.cgt_calc_args[1:])
        elif args.cgt_calc_args:
            cgt_calc_cmd.extend(args.cgt_calc_args)

        run_command(cgt_calc_cmd, f"Step {step_num}/{total_steps}: Running cgt-calc")

        # Cleanup intermediate files based on --keep-intermediates setting
        if args.keep_intermediates is None:
            # Default: delete all intermediates
            print("\n🧹 Cleaning up intermediate files...")
            transactions_raw_merged.unlink(missing_ok=True)
            awards_merged.unlink(missing_ok=True)
            transactions_merged.unlink(missing_ok=True)
            if initial_prices_merged:
                initial_prices_merged.unlink(missing_ok=True)
            if spin_offs_merged:
                spin_offs_merged.unlink(missing_ok=True)
            print("   Removed all intermediate CSV files")
        elif args.keep_intermediates == "finals":
            # Keep finals only
            print("\n🧹 Cleaning up temporary files...")
            transactions_raw_merged.unlink(missing_ok=True)
            print(f"   Removed {transactions_raw_merged.name}")
            print(f"   Kept {awards_merged.name}")
            print(f"   Kept {transactions_merged.name}")
            if initial_prices_merged:
                print(f"   Kept {initial_prices_merged.name}")
            if spin_offs_merged:
                print(f"   Kept {spin_offs_merged.name}")
        elif args.keep_intermediates == "A":
            # Keep everything
            print("\n📁 Kept all intermediate files:")
            print(f"   {transactions_raw_merged.name}")
            print(f"   {awards_merged.name}")
            print(f"   {transactions_merged.name}")
            if initial_prices_merged:
                print(f"   {initial_prices_merged.name}")
            if spin_offs_merged:
                print(f"   {spin_offs_merged.name}")
        else:
            print(f"\n⚠️  Unknown --keep-intermediates value: {args.keep_intermediates}")
            print("   Valid options: (no value) for finals only, 'A' for all")
            print("   Keeping all files by default...")

        print("\n" + "=" * 70)
        print("✨ All steps completed successfully!")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n\n⚠️  Process interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
