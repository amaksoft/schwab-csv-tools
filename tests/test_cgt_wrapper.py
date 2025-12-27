"""Tests for cgt_wrapper.py"""

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
