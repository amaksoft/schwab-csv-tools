"""Tests for cgt_wrapper.py"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from schwab_csv_tools.cgt_wrapper import run_command


class TestRunCommand:
    """Tests for run_command error detection."""

    def test_success_with_no_stderr(self, capsys):
        """Test successful command with no stderr output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stderr="",
            )

            run_command(["echo", "test"], "Test command")

            captured = capsys.readouterr()
            assert "✅ Test command completed successfully" in captured.out
            assert "❌" not in captured.out

    def test_success_with_non_critical_stderr(self, capsys):
        """Test successful command with non-critical stderr output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stderr="WARNING: Some warning message\nINFO: Processing...\n",
            )

            run_command(["echo", "test"], "Test command")

            captured = capsys.readouterr()
            assert "✅ Test command completed successfully" in captured.out
            assert "WARNING: Some warning message" in captured.err
            assert "❌" not in captured.out

    def test_failure_with_nonzero_exit_code(self, capsys):
        """Test that non-zero exit code is detected."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="",
            )

            with pytest.raises(SystemExit) as exc_info:
                run_command(["false"], "Test command")

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "❌ Error: Test command failed with exit code 1" in captured.out

    def test_failure_with_critical_in_stderr(self, capsys):
        """Test that CRITICAL: in stderr is detected even with exit code 0."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,  # Exit code 0 but has CRITICAL error
                stderr="CRITICAL: Unexpected error!\nSome details here\n",
            )

            with pytest.raises(SystemExit) as exc_info:
                run_command(["test"], "Test command")

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "❌ Error: Test command failed (critical error detected)" in captured.out
            assert "CRITICAL: Unexpected error!" in captured.err

    def test_failure_with_traceback_in_stderr(self, capsys):
        """Test that Traceback in stderr is detected even with exit code 0."""
        stderr_output = """ERROR: Details:
Traceback (most recent call last):
  File "/some/path/main.py", line 123, in main
    calculate_something()
IndexError: single positional indexer is out-of-bounds
"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,  # Exit code 0 but has Traceback
                stderr=stderr_output,
            )

            with pytest.raises(SystemExit) as exc_info:
                run_command(["test"], "Test command")

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "❌ Error: Test command failed (critical error detected)" in captured.out
            assert "Traceback" in captured.err

    def test_failure_with_both_critical_and_traceback(self, capsys):
        """Test that both CRITICAL and Traceback are detected."""
        stderr_output = """CRITICAL: Unexpected error!
ERROR: Details:
Traceback (most recent call last):
  File "/some/path/main.py", line 123, in main
    calculate_something()
IndexError: single positional indexer is out-of-bounds
"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,  # Exit code 0 but has both CRITICAL and Traceback
                stderr=stderr_output,
            )

            with pytest.raises(SystemExit) as exc_info:
                run_command(["test"], "Test command")

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "❌ Error: Test command failed (critical error detected)" in captured.out
            assert "CRITICAL: Unexpected error!" in captured.err
            assert "Traceback" in captured.err

    def test_failure_exit_code_takes_precedence(self, capsys):
        """Test that non-zero exit code takes precedence over critical errors."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2,
                stderr="CRITICAL: Error with non-zero exit\n",
            )

            with pytest.raises(SystemExit) as exc_info:
                run_command(["test"], "Test command")

            # Should exit with the actual exit code, not 1
            assert exc_info.value.code == 2
            captured = capsys.readouterr()
            assert "❌ Error: Test command failed with exit code 2" in captured.out
            # stderr should still be printed
            assert "CRITICAL: Error with non-zero exit" in captured.err

    def test_stdin_is_devnull(self):
        """Test that stdin is set to DEVNULL to prevent interactive prompts."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stderr="",
            )

            run_command(["echo", "test"], "Test command")

            # Verify stdin was set to DEVNULL
            call_args = mock_run.call_args
            assert call_args.kwargs["stdin"] == subprocess.DEVNULL

    def test_stderr_is_captured(self):
        """Test that stderr is captured using PIPE."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stderr="",
            )

            run_command(["echo", "test"], "Test command")

            # Verify stderr was set to PIPE
            call_args = mock_run.call_args
            assert call_args.kwargs["stderr"] == subprocess.PIPE


class TestArchiveDirections:
    """Test that archives are read-only inputs and write somewhere separate."""

    def test_rejects_output_dir_that_is_also_an_input(self, tmp_path, capsys):
        """Reading and writing one archive directory is refused.

        This is the invariant the whole split exists for: last year's archive
        is the only copy of history Schwab no longer exports, so a run must
        never be able to write over what it read.
        """
        import pytest

        from schwab_csv_tools.cgt_wrapper import check_archive_dirs_are_separate

        shared = tmp_path / "archive"
        shared.mkdir()

        with pytest.raises(SystemExit) as exit_info:
            check_archive_dirs_are_separate([str(shared)], str(shared))

        assert exit_info.value.code == 1
        assert "also an --archive-in directory" in capsys.readouterr().out

    def test_accepts_separate_dirs(self, tmp_path):
        """Distinct directories are fine."""
        from schwab_csv_tools.cgt_wrapper import check_archive_dirs_are_separate

        (tmp_path / "in").mkdir()
        check_archive_dirs_are_separate([str(tmp_path / "in")], str(tmp_path / "out"))

    def test_detects_shared_dir_through_a_different_path_spelling(self, tmp_path):
        """The comparison resolves paths, so './x' and 'x' are the same."""
        import pytest

        from schwab_csv_tools.cgt_wrapper import check_archive_dirs_are_separate

        shared = tmp_path / "archive"
        shared.mkdir()

        with pytest.raises(SystemExit):
            check_archive_dirs_are_separate(
                [str(shared)], str(shared / "." )
            )

    def test_collects_archive_files_by_name(self, tmp_path):
        """Transaction and awards archives are picked up separately."""
        from schwab_csv_tools.cgt_wrapper import collect_archive_inputs

        directory = tmp_path / "2024"
        directory.mkdir()
        (directory / "transactions_archive_2024.csv").write_text("Date\n")
        (directory / "awards_archive_2024.csv").write_text("Date\n")
        (directory / "notes.txt").write_text("ignored")

        transactions, awards = collect_archive_inputs([str(directory)])

        assert [Path(p).name for p in transactions] == [
            "transactions_archive_2024.csv"
        ]
        assert [Path(p).name for p in awards] == ["awards_archive_2024.csv"]

    def test_missing_archive_dir_is_an_error(self, tmp_path, capsys):
        """A typo in --archive-in must not silently drop history."""
        import pytest

        from schwab_csv_tools.cgt_wrapper import collect_archive_inputs

        with pytest.raises(SystemExit):
            collect_archive_inputs([str(tmp_path / "nope")])

        assert "not found" in capsys.readouterr().out

    def test_empty_archive_dir_is_an_error(self, tmp_path, capsys):
        """A directory with no archive files is a mistake, not an empty archive."""
        import pytest

        from schwab_csv_tools.cgt_wrapper import collect_archive_inputs

        directory = tmp_path / "2024"
        directory.mkdir()

        with pytest.raises(SystemExit):
            collect_archive_inputs([str(directory)])

        assert "no archive files" in capsys.readouterr().out
