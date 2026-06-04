#!/usr/bin/env python3
"""Extract and compare specific markdown sections between control and experiment outputs.

More useful than whole-file diff because the agents only write specific sections.
This extracts just the LLM-generated sections and shows side-by-side or unified diffs.

Usage:
    python3 section_diff.py <control_file> <experiment_file> [--sections "Meeting Prep,Digest"]
    python3 section_diff.py <control_dir> <experiment_dir> --daily-note
"""

import argparse
import difflib
import re
import sys
from pathlib import Path


# Sections written by each agent step
AGENT_SECTIONS = {
    "step6": ["### Meeting Prep", "### Active Projects", "### Upcoming Deadlines"],
    "step7": ["### Digest", "### Action Items"],
    "step7.5": ["## Dossier"],
    "step8": ["### Conversations"],
}

ALL_DAILY_SECTIONS = [
    "### Meeting Prep",
    "### Digest",
    "### Action Items",
    "### Active Projects",
    "### Upcoming Deadlines",
    "### Conversations",
]


def extract_section(content: str, heading: str) -> str | None:
    """Extract a markdown section from heading to next heading of same or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    pattern = rf"^{re.escape(heading)}\s*$"

    lines = content.split("\n")
    start = None
    end = None

    for i, line in enumerate(lines):
        if re.match(pattern, line.strip()):
            start = i
        elif start is not None and line.strip():
            # Check if this line is a heading of same or higher level
            m = re.match(r"^(#{1,6})\s+", line)
            if m and len(m.group(1)) <= level:
                end = i
                break

    if start is None:
        return None

    section_lines = lines[start : end if end else len(lines)]
    # Strip trailing blank lines
    while section_lines and not section_lines[-1].strip():
        section_lines.pop()
    return "\n".join(section_lines)


def count_wikilinks(text: str) -> dict:
    """Count and categorize wiki-links in text."""
    links = re.findall(r"\[\[([^\]]+)\]\]", text)
    categories = {"jira": 0, "people": 0, "meetings": 0, "prs": 0, "other": 0}
    for link in links:
        target = link.split("|")[0].split("\\|")[0]
        if target.startswith("jira/"):
            categories["jira"] += 1
        elif target.startswith("People/") or (not "/" in target and not target.startswith("#")):
            categories["people"] += 1
        elif target.startswith("Meetings/"):
            categories["meetings"] += 1
        elif target.startswith("prs/"):
            categories["prs"] += 1
        else:
            categories["other"] += 1
    return categories


def check_table_formatting(text: str) -> list[str]:
    """Check for common formatting errors in markdown tables."""
    issues = []
    in_table = False
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("|"):
            in_table = True
            # Check for unescaped pipes in wiki-links
            wikilinks = re.findall(r"\[\[([^\]]+)\]\]", line)
            for wl in wikilinks:
                if "|" in wl and "\\|" not in wl:
                    issues.append(f"Line {i}: unescaped pipe in wiki-link: [[{wl}]]")
        else:
            in_table = False
    return issues


def count_bullets(text: str) -> int:
    """Count top-level bullet points."""
    return sum(1 for line in text.split("\n") if re.match(r"^- ", line))


def count_checkboxes(text: str) -> tuple[int, int]:
    """Count unchecked and checked checkboxes."""
    unchecked = sum(1 for line in text.split("\n") if re.match(r"^- \[ \]", line))
    checked = sum(1 for line in text.split("\n") if re.match(r"^- \[x\]", line))
    return unchecked, checked


def analyze_section(text: str, heading: str) -> dict:
    """Produce structural metrics for a section."""
    if text is None:
        return {"present": False}

    lines = text.split("\n")
    return {
        "present": True,
        "lines": len(lines),
        "chars": len(text),
        "bullets": count_bullets(text),
        "checkboxes": count_checkboxes(text),
        "wikilinks": count_wikilinks(text),
        "table_issues": check_table_formatting(text),
        "subheadings": sum(1 for l in lines if re.match(r"^#{1,6}\s+", l)),
    }


def compare_file(control_path: Path, experiment_path: Path, sections: list[str]):
    """Compare specific sections between two files."""
    control_text = control_path.read_text() if control_path.exists() else ""
    experiment_text = experiment_path.read_text() if experiment_path.exists() else ""

    print(f"\n{'='*72}")
    print(f"FILE: {control_path.name}")
    print(f"{'='*72}")

    for heading in sections:
        ctrl_section = extract_section(control_text, heading)
        exp_section = extract_section(experiment_text, heading)

        print(f"\n--- {heading} ---")

        ctrl_info = analyze_section(ctrl_section, heading)
        exp_info = analyze_section(exp_section, heading)

        # Structural comparison
        print(f"  Control:    {'PRESENT' if ctrl_info['present'] else 'MISSING'}", end="")
        if ctrl_info["present"]:
            print(f" ({ctrl_info['lines']} lines, {ctrl_info['bullets']} bullets, "
                  f"{sum(ctrl_info['wikilinks'].values())} links)")
        else:
            print()

        print(f"  Experiment: {'PRESENT' if exp_info['present'] else 'MISSING'}", end="")
        if exp_info["present"]:
            print(f" ({exp_info['lines']} lines, {exp_info['bullets']} bullets, "
                  f"{sum(exp_info['wikilinks'].values())} links)")
        else:
            print()

        # Table formatting issues
        for label, info in [("Control", ctrl_info), ("Experiment", exp_info)]:
            if info["present"] and info["table_issues"]:
                print(f"  {label} TABLE ISSUES:")
                for issue in info["table_issues"]:
                    print(f"    - {issue}")

        # Show diff if both present and different
        if ctrl_section and exp_section and ctrl_section != exp_section:
            diff = difflib.unified_diff(
                ctrl_section.split("\n"),
                exp_section.split("\n"),
                fromfile=f"control",
                tofile=f"experiment",
                lineterm="",
            )
            diff_lines = list(diff)
            if len(diff_lines) > 60:
                print(f"  Diff ({len(diff_lines)} lines, showing first 60):")
                for line in diff_lines[:60]:
                    print(f"  {line}")
                print(f"  ... ({len(diff_lines) - 60} more lines)")
            else:
                print(f"  Diff:")
                for line in diff_lines:
                    print(f"  {line}")
        elif ctrl_section and not exp_section:
            print(f"  Experiment MISSING this section (control has {ctrl_info['lines']} lines)")
        elif exp_section and not ctrl_section:
            print(f"  Control MISSING this section (experiment has {exp_info['lines']} lines)")


def main():
    parser = argparse.ArgumentParser(description="Compare LLM-generated markdown sections")
    parser.add_argument("control", help="Control file or directory")
    parser.add_argument("experiment", help="Experiment file or directory")
    parser.add_argument("--sections", help="Comma-separated section headings to compare")
    parser.add_argument("--daily-note", action="store_true",
                       help="Compare all daily note sections")
    parser.add_argument("--step", help="Compare sections for a specific agent step (6,7,7.5,8)")
    parser.add_argument("--people", action="store_true",
                       help="Compare ## Dossier sections in People/ pages")
    args = parser.parse_args()

    control = Path(args.control)
    experiment = Path(args.experiment)

    if args.sections:
        sections = [s.strip() for s in args.sections.split(",")]
    elif args.step:
        sections = AGENT_SECTIONS.get(f"step{args.step}", [])
        if not sections:
            print(f"Unknown step: {args.step}")
            sys.exit(1)
    elif args.daily_note:
        sections = ALL_DAILY_SECTIONS
    elif args.people:
        sections = ["## Dossier"]
    else:
        sections = ALL_DAILY_SECTIONS

    if control.is_file() and experiment.is_file():
        compare_file(control, experiment, sections)
    elif control.is_dir() and experiment.is_dir():
        # Find matching files
        if args.people:
            ctrl_files = sorted(control.glob("People/*.md"))
            for cf in ctrl_files:
                ef = experiment / cf.relative_to(control)
                if ef.exists():
                    compare_file(cf, ef, sections)
        else:
            # Find daily note
            ctrl_daily = list(control.rglob("daily/*/*.md"))
            for cf in ctrl_daily:
                ef = experiment / cf.relative_to(control)
                if ef.exists():
                    compare_file(cf, ef, sections)
    else:
        print("Error: both arguments must be files or both must be directories")
        sys.exit(1)


if __name__ == "__main__":
    main()
