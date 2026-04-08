#!/usr/bin/env python3
"""
Detailed analysis script for daily note cleanup candidates.
"""
import os
from pathlib import Path

def analyze_file_detailed(file_path):
    """Detailed analysis of a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None

    lines = content.split('\n')
    headers = []
    for i, line in enumerate(lines):
        if line.strip().startswith('### '):
            headers.append((i, line.strip()))

    if not headers:
        return None

    analysis = {
        'file_path': file_path,
        'total_sections': 0,
        'empty_sections': 0,
        'sections': []
    }

    for i in range(len(headers)):
        header_text = headers[i][1]

        # Skip dataview sections
        if 'notes created today' in header_text.lower() or 'notes modified today' in header_text.lower():
            continue

        start_line = headers[i][0] + 1
        if i + 1 < len(headers):
            end_line = headers[i + 1][0]
        else:
            end_line = len(lines)

        section_lines = lines[start_line:end_line]
        non_empty_lines = [line.strip() for line in section_lines if line.strip()]

        is_empty = False
        if not non_empty_lines:
            is_empty = True
        elif len(non_empty_lines) == 1 and non_empty_lines[0] == '-':
            is_empty = True
        elif all(line == '-' for line in non_empty_lines):
            is_empty = True

        analysis['sections'].append({
            'header': header_text,
            'is_empty': is_empty,
            'line_count': len(non_empty_lines)
        })

        analysis['total_sections'] += 1
        if is_empty:
            analysis['empty_sections'] += 1

    return analysis

def main():
    daily_dir = Path(__file__).resolve().parents[3] / "daily"

    all_files = []
    for root, dirs, files in os.walk(daily_dir):
        for file in files:
            if file.endswith('.md') and not file.startswith('.') and 'sync-conflict' not in file:
                all_files.append(os.path.join(root, file))

    total_files = len(all_files)
    files_needing_cleanup = 0
    completely_empty_files = 0
    mostly_empty_files = 0

    print("Detailed Analysis of Daily Notes")
    print("=" * 50)

    # Analyze some representative files in detail for examples
    print("\nSample Analysis:")
    sample_files = sorted(all_files)[::40][:8]  # Every 40th file for good spread

    for i, file_path in enumerate(sample_files):
        analysis = analyze_file_detailed(file_path)
        if analysis and analysis['total_sections'] > 0:
            rel_path = os.path.relpath(file_path, daily_dir)
            empty_ratio = analysis['empty_sections'] / analysis['total_sections']

            print(f"\n{i+1}. {rel_path}")
            print(f"   Sections: {analysis['total_sections']}, Empty: {analysis['empty_sections']} ({empty_ratio:.1%})")

            for section in analysis['sections']:
                status = "EMPTY" if section['is_empty'] else f"{section['line_count']} lines"
                print(f"   - {section['header']}: {status}")

    # Count overall statistics
    for file_path in all_files:
        analysis = analyze_file_detailed(file_path)
        if analysis and analysis['total_sections'] > 0:
            empty_ratio = analysis['empty_sections'] / analysis['total_sections']

            if analysis['empty_sections'] == analysis['total_sections']:
                completely_empty_files += 1
                files_needing_cleanup += 1
            elif empty_ratio >= 0.5:  # More than half empty
                mostly_empty_files += 1
                files_needing_cleanup += 1
            elif analysis['empty_sections'] >= 2:  # At least 2 empty sections
                files_needing_cleanup += 1

    print(f"\n\nOVERALL STATISTICS:")
    print(f"Total daily note files: {total_files}")
    print(f"Files with completely empty sections: {completely_empty_files}")
    print(f"Files with mostly empty sections (50%+ empty): {mostly_empty_files}")
    print(f"Total files needing cleanup: {files_needing_cleanup}")
    print(f"Cleanup percentage: {files_needing_cleanup/total_files*100:.1f}%")

if __name__ == "__main__":
    main()
