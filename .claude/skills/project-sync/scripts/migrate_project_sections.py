#!/usr/bin/env python3
"""Migrate project notes to use %% section:name %% markers.

For each project note with standard frontmatter (status/pipeline fields),
wraps recognized ## sections in markers without changing content.

Sections mapped:
  ## Status / ## Current State         -> section:status
  ## Goal / ## What Is It / ## Overview -> section:goal
  ## Team                              -> section:team
  ## Timeline                          -> section:timeline
  ## Related Items                     -> section:related-items
  Everything else between known sections -> folded into section:notes

Usage:
  python3 migrate_project_sections.py <vault_dir> [--dry-run]
"""

import re
import sys
from pathlib import Path

SECTION_MAP = {
    "## Status": "status",
    "## Current State": "status",
    "## Goal": "goal",
    "## What Is It": "goal",
    "## Overview": "goal",
    "## Team": "team",
    "## Timeline": "timeline",
    "## Related Items": "related-items",
}

KNOWN_SECTIONS = ["status", "goal", "team", "timeline", "notes", "related-items"]

SKIP_FILES = [
    "Status Report Gap Analysis.md",
    "GPT4 Generated Story.md",
    "Excursions Bucket List.md",
    "Desk Wiring.md",
]


def has_project_frontmatter(text: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    fm = text[3:end]
    return "pipeline:" in fm or "status:" in fm


def find_sections(lines: list[str]) -> list[dict]:
    """Find all ## headings and their line ranges."""
    sections = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            heading = line.rstrip()
            sections.append({"heading": heading, "start": i, "end": None})
    for i, sec in enumerate(sections):
        sec["end"] = sections[i + 1]["start"] if i + 1 < len(sections) else len(lines)
    return sections


def already_migrated(text: str) -> bool:
    return "%% section:" in text


def migrate_note(path: Path, dry_run: bool = False) -> bool:
    text = path.read_text()

    if already_migrated(text):
        return False

    if not has_project_frontmatter(text):
        return False

    lines = text.split("\n")

    fm_end = -1
    if lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
    if fm_end < 0:
        return False

    sections = find_sections(lines)
    if not sections:
        return False

    mapped = []
    notes_chunks = []

    for sec in sections:
        heading_stripped = sec["heading"].rstrip()
        marker = None
        for pattern, name in SECTION_MAP.items():
            if heading_stripped == pattern or heading_stripped.startswith(pattern + " "):
                marker = name
                break

        if marker:
            mapped.append({**sec, "marker": marker})
        else:
            notes_chunks.append(sec)

    result_lines = lines[: fm_end + 1]

    intro_start = fm_end + 1
    intro_end = sections[0]["start"] if sections else len(lines)
    intro = lines[intro_start:intro_end]
    result_lines.extend(intro)

    emitted_markers = set()

    for marker_name in KNOWN_SECTIONS:
        if marker_name == "notes":
            if notes_chunks:
                result_lines.append(f"%% section:notes %%")
                for chunk in notes_chunks:
                    chunk_lines = lines[chunk["start"]:chunk["end"]]
                    while chunk_lines and chunk_lines[-1].strip() == "":
                        chunk_lines.pop()
                    result_lines.extend(chunk_lines)
                    result_lines.append("")
                result_lines.append(f"%% /section:notes %%")
                result_lines.append("")
                emitted_markers.add("notes")
            continue

        matches = [m for m in mapped if m["marker"] == marker_name]
        if not matches:
            if marker_name == "related-items":
                result_lines.append(f"%% section:related-items %%")
                result_lines.append("## Related Items")
                result_lines.append("")
                result_lines.append(f"%% /section:related-items %%")
                result_lines.append("")
            continue

        sec = matches[0]
        sec_lines = lines[sec["start"]:sec["end"]]
        while sec_lines and sec_lines[-1].strip() == "":
            sec_lines.pop()

        result_lines.append(f"%% section:{marker_name} %%")
        result_lines.extend(sec_lines)
        result_lines.append("")
        result_lines.append(f"%% /section:{marker_name} %%")
        result_lines.append("")
        emitted_markers.add(marker_name)

    if not result_lines[-1].strip() == "":
        result_lines.append("")

    new_text = "\n".join(result_lines)

    if dry_run:
        print(f"  WOULD migrate: {path.name}")
        print(f"    Mapped sections: {[m['marker'] for m in mapped]}")
        print(f"    Notes chunks: {[c['heading'] for c in notes_chunks]}")
        return True

    path.write_text(new_text)
    print(f"  Migrated: {path.name}")
    print(f"    Sections: {', '.join(s for s in KNOWN_SECTIONS if s in emitted_markers or (s == 'notes' and notes_chunks))}")
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <vault_dir> [--dry-run]")
        sys.exit(1)

    vault = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    projects_dir = vault / "Projects"
    if not projects_dir.exists():
        print(f"Error: {projects_dir} not found")
        sys.exit(1)

    notes = sorted(projects_dir.rglob("*.md"))
    notes = [n for n in notes if "Archived" not in str(n) and "Summit 2026" not in str(n)]
    notes = [n for n in notes if n.name not in SKIP_FILES]

    migrated = 0
    skipped = 0
    for note in notes:
        if migrate_note(note, dry_run):
            migrated += 1
        else:
            rel = note.relative_to(vault)
            reason = "already migrated" if already_migrated(note.read_text()) else "no project frontmatter"
            print(f"  Skipped: {rel} ({reason})")
            skipped += 1

    print(f"\nDone: {migrated} migrated, {skipped} skipped")


if __name__ == "__main__":
    main()
