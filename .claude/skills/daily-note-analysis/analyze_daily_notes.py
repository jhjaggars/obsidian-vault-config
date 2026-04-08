#!/usr/bin/env python3
"""
Script to analyze daily note files and count how many need cleanup.
Identifies files with empty sections between headers.
"""
import os
import re
from pathlib import Path

def analyze_daily_note(file_path):
    """
    Analyze a single daily note file for empty sections.
    Returns True if the file needs cleanup, False otherwise.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return False

    # Split content into lines
    lines = content.split('\n')

    # Find all headers (lines starting with ###)
    headers = []
    for i, line in enumerate(lines):
        if line.strip().startswith('### '):
            headers.append((i, line.strip()))

    if not headers:
        return False

    empty_sections_count = 0
    total_sections = 0

    # Check each section between headers
    for i in range(len(headers)):
        header_text = headers[i][1].lower()

        # Skip dataview sections as they're functional
        if 'notes created today' in header_text or 'notes modified today' in header_text:
            continue

        total_sections += 1
        start_line = headers[i][0] + 1  # Line after header

        # Find end line (next header or end of file)
        if i + 1 < len(headers):
            end_line = headers[i + 1][0]
        else:
            end_line = len(lines)

        # Extract section content
        section_lines = lines[start_line:end_line]

        # Remove empty lines and strip whitespace
        non_empty_lines = [line.strip() for line in section_lines if line.strip()]

        # Check for empty sections or sections with only empty bullet points
        is_empty = False
        if not non_empty_lines:
            # Completely empty section
            is_empty = True
        elif len(non_empty_lines) == 1 and non_empty_lines[0] == '-':
            # Section with only empty bullet point
            is_empty = True
        elif all(line == '-' for line in non_empty_lines):
            # Section with only empty bullet points
            is_empty = True

        if is_empty:
            empty_sections_count += 1

    # Consider a file as needing cleanup if it has at least one empty section
    # and more than 30% of its sections are empty
    if total_sections == 0:
        return False

    return empty_sections_count > 0 and (empty_sections_count / total_sections) >= 0.3

def find_all_daily_notes(base_path):
    """Find all daily note files."""
    daily_notes = []

    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith('.md') and not file.startswith('.'):
                # Skip sync conflict files
                if 'sync-conflict' not in file:
                    daily_notes.append(os.path.join(root, file))

    return sorted(daily_notes)

def main():
    daily_dir = Path(__file__).resolve().parents[3] / "daily"

    if not daily_dir.exists():
        print(f"Directory not found: {daily_dir}")
        return

    print("Analyzing daily note files for cleanup candidates...")
    print("=" * 60)

    all_files = find_all_daily_notes(daily_dir)
    cleanup_candidates = []

    for file_path in all_files:
        if analyze_daily_note(file_path):
            cleanup_candidates.append(file_path)

    print(f"Total daily note files analyzed: {len(all_files)}")
    print(f"Files that need cleanup: {len(cleanup_candidates)}")
    print(f"Cleanup percentage: {(len(cleanup_candidates)/len(all_files)*100):.1f}%")

    print("\nSample files that need cleanup:")
    for i, file_path in enumerate(cleanup_candidates[:10]):
        rel_path = os.path.relpath(file_path, daily_dir)
        print(f"  {i+1}. {rel_path}")

    if len(cleanup_candidates) > 10:
        print(f"  ... and {len(cleanup_candidates) - 10} more files")

    return len(cleanup_candidates)

if __name__ == "__main__":
    main()
