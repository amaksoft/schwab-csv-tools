#!/usr/bin/env python3
"""Merge initial prices and spin-offs configuration files for cgt-calc."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def merge_initial_prices(
    input_files: list[Path], output_file: Path, verbose: bool = False
) -> None:
    """Merge multiple initial_prices.csv files.

    Files should have format: date,symbol,price
    Duplicates (same date+symbol) are deduplicated, keeping the last occurrence.

    Args:
        input_files: List of initial_prices.csv files to merge
        output_file: Path to write merged output
        verbose: Print detailed processing info
    """
    if verbose:
        print(f"Merging {len(input_files)} initial prices file(s)...")

    # Dictionary to store prices: (date, symbol) -> price
    prices: dict[tuple[str, str], str] = {}

    for filepath in input_files:
        if verbose:
            print(f"  Reading {filepath}")

        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row["date"]
                symbol = row["symbol"]
                price = row["price"]
                key = (date, symbol)

                # Keep last occurrence if duplicate
                if key in prices:
                    if verbose:
                        print(
                            f"    Duplicate found: {date}, {symbol} "
                            f"(keeping last: {price})"
                        )
                prices[key] = price

    # Write merged output
    if verbose:
        print(f"  Writing {len(prices)} price(s) to {output_file}")

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "symbol", "price"])
        for (date, symbol), price in sorted(prices.items()):
            writer.writerow([date, symbol, price])

    if verbose:
        print(f"✓ Merged {len(prices)} initial price(s)")


def merge_spin_offs(
    input_files: list[Path], output_file: Path, verbose: bool = False
) -> None:
    """Merge multiple spin_offs.csv files.

    Files should have format: dst,src
    Duplicates (same dst) are deduplicated, keeping the last occurrence.

    Args:
        input_files: List of spin_offs.csv files to merge
        output_file: Path to write merged output
        verbose: Print detailed processing info
    """
    if verbose:
        print(f"Merging {len(input_files)} spin-offs file(s)...")

    # Dictionary to store spin-offs: dst -> src
    spin_offs: dict[str, str] = {}

    for filepath in input_files:
        if verbose:
            print(f"  Reading {filepath}")

        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dst = row["dst"]
                src = row["src"]

                # Keep last occurrence if duplicate
                if dst in spin_offs:
                    if verbose:
                        print(
                            f"    Duplicate found: {dst} -> {spin_offs[dst]} "
                            f"(replacing with {src})"
                        )
                spin_offs[dst] = src

    # Write merged output
    if verbose:
        print(f"  Writing {len(spin_offs)} spin-off(s) to {output_file}")

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["dst", "src"])
        for dst, src in sorted(spin_offs.items()):
            writer.writerow([dst, src])

    if verbose:
        print(f"✓ Merged {len(spin_offs)} spin-off(s)")


def main() -> None:
    """Main entry point for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Merge initial prices or spin-offs configuration files"
    )
    parser.add_argument(
        "file_type",
        choices=["initial-prices", "spin-offs"],
        help="Type of file to merge",
    )
    parser.add_argument(
        "input_files", nargs="+", type=Path, help="Input CSV files to merge"
    )
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="Output merged CSV file"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed processing info"
    )

    args = parser.parse_args()

    try:
        if args.file_type == "initial-prices":
            merge_initial_prices(args.input_files, args.output, args.verbose)
        elif args.file_type == "spin-offs":
            merge_spin_offs(args.input_files, args.output, args.verbose)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
