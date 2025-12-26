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


def run_command(cmd: list[str], description: str) -> None:
    """Run a command and handle errors.

    Checks both exit code and output for error indicators.
    """
    print(f"\n{'=' * 70}")
    print(f"{description}")
    print(f"{'=' * 70}")
    print(f"$ {' '.join(cmd)}\n")

    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True
    )

    # Print output in real-time style
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)

    # Check for critical errors in output (cgt-calc returns 0 even on errors)
    output_combined = (result.stdout or '') + (result.stderr or '')
    has_critical_error = (
        'CRITICAL:' in output_combined or 'Traceback' in output_combined
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

  # With optional symbol mapping and specific output directory
  cgt-calc-wrapper \\
    --transactions tx1.csv tx2.csv \\
    --awards awards1.csv awards2.csv \\
    --symbol-mapping mappings.csv \\
    --output-dir ./processed \\
    --year 2024 \\
    --pdf output.pdf

  # Pass additional cgt-calc arguments
  cgt-calc-wrapper \\
    --transactions tx.csv \\
    --awards awards.csv \\
    --year 2024 \\
    -- --initial-prices initial.csv --verbose
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

    # Processing options
    parser.add_argument(
        "--symbol-mapping",
        "-m",
        metavar="FILE",
        help="CSV file mapping descriptions to symbols (optional)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        metavar="DIR",
        default=".",
        help="Directory for intermediate processed files (default: current directory)",
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

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Define intermediate file paths
    transactions_raw_merged = output_dir / f"transactions_raw_merged_{args.year}.csv"
    awards_merged = output_dir / f"awards_merged_{args.year}.csv"
    transactions_merged = output_dir / f"transactions_merged_{args.year}.csv"

    try:
        # Step 1: Merge transaction files
        merge_tx_cmd = [
            find_script_in_same_env("merge-schwab-csv"),
            "-o",
            str(transactions_raw_merged),
            *args.transactions,
        ]
        if args.verbose:
            merge_tx_cmd.append("-v")
        run_command(merge_tx_cmd, "Step 1/4: Merging transaction files")

        # Step 2: Merge equity awards files
        merge_awards_cmd = [
            find_script_in_same_env("merge-schwab-awards"),
            "-o",
            str(awards_merged),
            *args.awards,
        ]
        if args.verbose:
            merge_awards_cmd.append("-v")
        run_command(merge_awards_cmd, "Step 2/4: Merging equity awards files")

        # Step 3: Postprocess transactions
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
        if args.verbose:
            postprocess_cmd.append("-v")
        run_command(postprocess_cmd, "Step 3/4: Postprocessing transactions")

        # Step 4: Run cgt-calc
        cgt_calc_cmd = [
            str(cgt_calc),
            "--schwab-file",
            str(transactions_merged),
            "--schwab-award-file",
            str(awards_merged),
            "--year",
            str(args.year),
        ]

        if args.pdf:
            cgt_calc_cmd.extend(["--output", args.pdf])

        # Add any additional arguments (after --)
        if args.cgt_calc_args and args.cgt_calc_args[0] == "--":
            cgt_calc_cmd.extend(args.cgt_calc_args[1:])
        elif args.cgt_calc_args:
            cgt_calc_cmd.extend(args.cgt_calc_args)

        run_command(cgt_calc_cmd, "Step 4/4: Running cgt-calc")

        # Cleanup intermediate files based on --keep-intermediates setting
        if args.keep_intermediates is None:
            # Default: delete all intermediates
            print("\n🧹 Cleaning up intermediate files...")
            transactions_raw_merged.unlink(missing_ok=True)
            awards_merged.unlink(missing_ok=True)
            transactions_merged.unlink(missing_ok=True)
            print("   Removed all intermediate CSV files")
        elif args.keep_intermediates == "finals":
            # Keep finals only
            print("\n🧹 Cleaning up temporary files...")
            transactions_raw_merged.unlink(missing_ok=True)
            print(f"   Removed {transactions_raw_merged.name}")
            print(f"   Kept {awards_merged.name}")
            print(f"   Kept {transactions_merged.name}")
        elif args.keep_intermediates == "A":
            # Keep everything
            print(f"\n📁 Kept all intermediate files:")
            print(f"   {transactions_raw_merged.name}")
            print(f"   {awards_merged.name}")
            print(f"   {transactions_merged.name}")
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
