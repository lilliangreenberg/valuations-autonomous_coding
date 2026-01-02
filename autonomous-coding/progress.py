"""
Progress Tracking Utilities
===========================

Functions for tracking and displaying progress of the autonomous coding agent.
"""

from pathlib import Path


def count_passing_tests(project_dir: Path) -> tuple[int, int]:
    """
    Count passing and total feature files by checking @passing/@failing tags.

    Args:
        project_dir: Directory containing gherkin.feature_*.feature files

    Returns:
        (passing_count, total_count)
    """
    # Find all feature files
    feature_files = list(project_dir.glob("gherkin.feature_*.feature"))

    if not feature_files:
        return 0, 0

    total = len(feature_files)
    passing = 0

    for feature_file in feature_files:
        try:
            with open(feature_file, "r", encoding="utf-8") as f:
                # Read first few lines to find the tag
                for line in f:
                    line = line.strip()
                    if line.startswith("@passing"):
                        passing += 1
                        break
                    elif line.startswith("@failing"):
                        # Found failing tag, don't increment passing counter
                        break
                    elif line and not line.startswith("#"):
                        # Hit non-comment, non-tag line - assume no tag found
                        break
        except (IOError, UnicodeDecodeError):
            # If we can't read the file, don't count it as passing
            continue

    return passing, total


def count_failing_features(project_dir: Path) -> int:
    """
    Count features marked as @failing.

    Args:
        project_dir: Directory containing gherkin.feature_*.feature files

    Returns:
        Number of features with @failing tag
    """
    # Find all feature files
    feature_files = list(project_dir.glob("gherkin.feature_*.feature"))

    if not feature_files:
        return 0

    failing = 0

    for feature_file in feature_files:
        try:
            with open(feature_file, "r", encoding="utf-8") as f:
                # Read first few lines to find the tag
                for line in f:
                    line = line.strip()
                    if line.startswith("@failing"):
                        failing += 1
                        break
                    elif line.startswith("@passing"):
                        # Found passing tag, skip this file
                        break
                    elif line and not line.startswith("#"):
                        # Hit non-comment, non-tag line - assume no tag found
                        break
        except (IOError, UnicodeDecodeError):
            # If we can't read the file, skip it
            continue

    return failing


def print_session_header(session_num: int, is_initializer: bool) -> None:
    """Print a formatted header for the session."""
    session_type = "INITIALIZER" if is_initializer else "CODING AGENT"

    print("\n" + "=" * 70)
    print(f"  SESSION {session_num}: {session_type}")
    print("=" * 70)
    print()


def print_progress_summary(project_dir: Path) -> None:
    """Print a summary of current progress."""
    passing, total = count_passing_tests(project_dir)

    if total > 0:
        percentage = (passing / total) * 100
        print(f"\nProgress: {passing}/{total} feature files passing ({percentage:.1f}%)")
    else:
        print("\nProgress: No feature files created yet")
