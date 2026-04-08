#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Sync active projects from Work Pipeline.md with related JIRA issues,
GitHub PRs, Drive docs, and recent meeting notes. Writes a ## Related Items
section into each project note.

Usage: uv run project_sync.py /path/to/vault
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "has", "in",
    "is", "it", "its", "of", "on", "or", "the", "to", "was", "with",
    "support", "project",  # too generic for matching
}

# Months for path parsing
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# Check if obsidian CLI is available (PATH or known app bundle location)
_OBSIDIAN_APP_PATH = "/Applications/Obsidian.app/Contents/MacOS/obsidian"
OBSIDIAN_BIN = shutil.which("obsidian") or (
    _OBSIDIAN_APP_PATH if Path(_OBSIDIAN_APP_PATH).is_file() else None
)
CLI_AVAILABLE = OBSIDIAN_BIN is not None


def cli_search(query: str, path: str) -> list[dict]:
    """Run obsidian search and return parsed JSON results. Returns [] on failure."""
    if not OBSIDIAN_BIN:
        return []
    try:
        result = subprocess.run(
            [OBSIDIAN_BIN, "search", f'query="{query}"', f'path="{path}"', "format=json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return []


def cli_backlinks(file_path: str) -> list[dict]:
    """Run obsidian backlinks and return parsed JSON results. Returns [] on failure."""
    if not OBSIDIAN_BIN:
        return []
    try:
        result = subprocess.run(
            [OBSIDIAN_BIN, "backlinks", f'file="{file_path}"', "format=json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return []


def parse_frontmatter(text: str) -> dict:
    """Parse simple YAML frontmatter from note text. Returns dict of key-value pairs."""
    fm = {}
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return fm
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        fm[key] = val
    return fm


def parse_frontmatter_fast(path: Path, max_lines: int = 20) -> dict:
    """Read only the first max_lines of a file and parse frontmatter."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
        return parse_frontmatter("".join(lines))
    except OSError:
        return {}


def parse_keywords_field(text: str) -> list[str]:
    """Parse a keywords field value. Handles ["a", "b"] or bare comma-separated."""
    text = text.strip()
    # Handle ["a", "b"] or ['a', 'b']
    if text.startswith("["):
        text = text.strip("[]")
        return [k.strip().strip('"').strip("'") for k in text.split(",") if k.strip()]
    # Handle bare comma-separated
    if "," in text:
        return [k.strip() for k in text.split(",") if k.strip()]
    # Single value
    return [text] if text else []


def parse_work_pipeline(vault: Path) -> list[dict]:
    """Read Work Pipeline.md and extract active projects from Early and Mature columns."""
    pipeline = vault / "Work Pipeline.md"
    if not pipeline.exists():
        print(f"ERROR: {pipeline} not found", file=sys.stderr)
        return []

    text = pipeline.read_text(encoding="utf-8")
    projects = []
    in_active_section = False

    for line in text.split("\n"):
        stripped = line.strip()

        # Track which section we're in
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            in_active_section = heading in ("Early", "Mature")
            continue

        if not in_active_section:
            continue

        # Extract wiki-links from list items
        match = re.search(r"\[\[(.+?)]]", stripped)
        if match:
            name = match.group(1)
            # Resolve to file path
            note_path = resolve_project_path(vault, name)
            projects.append({
                "name": name,
                "path": note_path,
            })

    return projects


def resolve_project_path(vault: Path, name: str) -> Path | None:
    """Resolve a wiki-link name to a project file path."""
    # Try direct path first
    direct = vault / "Projects" / "Work" / f"{name}.md"
    if direct.exists():
        return direct

    # Search subdirectories
    for path in (vault / "Projects" / "Work").rglob(f"{name}.md"):
        return path

    return None


def strip_related_items(text: str) -> str:
    """Remove the ## Related Items section (auto-generated) to avoid feedback loops."""
    match = re.search(r"^## Related Items\s*$", text, re.MULTILINE)
    if not match:
        return text
    # Find the next ## heading after Related Items, or use EOF
    rest = text[match.end():]
    next_heading = re.search(r"^## ", rest, re.MULTILINE)
    if next_heading:
        return text[:match.start()] + rest[next_heading.start():]
    return text[:match.start()]


def extract_match_criteria(note_path: Path, project_name: str) -> dict:
    """Extract JIRA keys, keywords, and repo names from a project note."""
    criteria = {
        "jira_keys": set(),
        "keywords": [],
        "repo_names": set(),
    }

    text = ""
    fm = {}
    if note_path and note_path.exists():
        raw = note_path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(raw)
        # Strip the auto-generated Related Items section to prevent feedback loops
        text = strip_related_items(raw)

    # 1. JIRA keys — regex scan for [A-Z]+-\d+ patterns
    for match in re.finditer(r"\b([A-Z][A-Z0-9]+-\d+)\b", text):
        criteria["jira_keys"].add(match.group(1))

    # 2. Keywords — from frontmatter field or title
    if "keywords" in fm:
        criteria["keywords"] = parse_keywords_field(fm["keywords"])
    else:
        criteria["keywords"] = keywords_from_title(project_name)

    # 3. Repo names — from explicit github.com URLs only (not prs/ wiki-links,
    #    which would cause over-matching on common repos like "hypershift")
    for match in re.finditer(r"github\.com/[^/]+/([a-zA-Z0-9_.-]+)", text):
        criteria["repo_names"].add(match.group(1).rstrip("/"))

    return criteria


def keywords_from_title(title: str) -> list[str]:
    """Derive keywords from a project title."""
    # Remove JIRA key prefix if present (e.g., "OCPSTRAT-2666 BGP ROSA HCP")
    cleaned = re.sub(r"^[A-Z][A-Z0-9]+-\d+\s*", "", title)

    words = []
    for w in cleaned.split():
        lower = w.lower()
        if lower not in STOP_WORDS and len(lower) > 1:
            words.append(w)

    keywords = []

    # Add individual words (preserve case for acronyms)
    for w in words:
        keywords.append(w)

    # Add bigrams from consecutive words
    for i in range(len(words) - 1):
        keywords.append(f"{words[i]} {words[i+1]}")

    return keywords


def scan_jira(vault: Path, criteria: dict) -> list[dict]:
    """Scan jira/*.md for matches against criteria. Uses CLI when available."""
    jira_dir = vault / "jira"
    if not jira_dir.exists():
        return []

    matches = []
    matched_keys = set()

    # --- CLI-accelerated path ---
    if CLI_AVAILABLE:
        # Search by each JIRA key and keyword via CLI
        search_terms = list(criteria["jira_keys"]) + criteria["keywords"]
        for term in search_terms:
            results = cli_search(term, "jira/")
            for r in results:
                file_path = r.get("path", r.get("file", ""))
                if not file_path:
                    continue
                # Extract key from path (e.g., "jira/HCMSTRAT-15.md" -> "HCMSTRAT-15")
                key = Path(file_path).stem
                if key in matched_keys:
                    continue
                # Read frontmatter for details
                jira_file = vault / file_path if not (vault / file_path).suffix else vault / file_path
                if not file_path.endswith(".md"):
                    jira_file = vault / f"{file_path}.md"
                else:
                    jira_file = vault / file_path
                fm = parse_frontmatter_fast(jira_file) if jira_file.exists() else {}
                matched_keys.add(key)
                matches.append({
                    "key": fm.get("key", key),
                    "summary": fm.get("summary", ""),
                    "status": fm.get("status", ""),
                    "path": f"jira/{key}",
                    "match_type": "cli",
                })
        return matches

    # --- File-based fallback ---
    # 1. Exact key matches
    for key in criteria["jira_keys"]:
        jira_file = jira_dir / f"{key}.md"
        if jira_file.exists():
            fm = parse_frontmatter_fast(jira_file)
            if key not in matched_keys:
                matched_keys.add(key)
                matches.append({
                    "key": fm.get("key", key),
                    "summary": fm.get("summary", ""),
                    "status": fm.get("status", ""),
                    "path": f"jira/{key}",
                    "match_type": "key",
                })

    # 2. Keyword matches in summary field
    if criteria["keywords"]:
        for jira_file in jira_dir.glob("*.md"):
            key = jira_file.stem
            if key in matched_keys:
                continue
            fm = parse_frontmatter_fast(jira_file)
            summary = fm.get("summary", "").lower()
            if not summary:
                continue
            for kw in criteria["keywords"]:
                if kw.lower() in summary:
                    matched_keys.add(key)
                    matches.append({
                        "key": fm.get("key", key),
                        "summary": fm.get("summary", ""),
                        "status": fm.get("status", ""),
                        "path": f"jira/{key}",
                        "match_type": "keyword",
                    })
                    break

    return matches


def scan_prs(vault: Path, criteria: dict) -> list[dict]:
    """Scan prs/*.md for matches against criteria."""
    prs_dir = vault / "prs"
    if not prs_dir.exists():
        return []

    matches = []
    matched_files = set()

    for pr_file in prs_dir.glob("*.md"):
        stem = pr_file.stem
        if stem in matched_files:
            continue

        fm = parse_frontmatter_fast(pr_file)
        title = fm.get("title", "").lower()
        repo_name = fm.get("repo_name", "")
        number = fm.get("number", "")
        draft = fm.get("draft", "false").lower() == "true"

        matched = False

        # Match by repo name
        if repo_name and repo_name in criteria["repo_names"]:
            matched = True

        # Match by keyword in title
        if not matched and criteria["keywords"]:
            for kw in criteria["keywords"]:
                if kw.lower() in title:
                    matched = True
                    break

        # Match by JIRA key in filename or title
        if not matched:
            for key in criteria["jira_keys"]:
                if key.lower() in stem.lower() or key.lower() in title:
                    matched = True
                    break

        if matched:
            matched_files.add(stem)
            status = "Draft" if draft else "Open"
            display = f"{repo_name}#{number}" if repo_name and number else stem
            matches.append({
                "filename": stem,
                "title": fm.get("title", ""),
                "repo_name": repo_name,
                "number": number,
                "status": status,
                "display": display,
                "path": f"prs/{stem}",
            })

    return matches


def scan_drive(vault: Path, criteria: dict) -> list[dict]:
    """Scan top-level Drive/*.md filenames for keyword matches."""
    drive_dir = vault / "Drive"
    if not drive_dir.exists():
        return []

    if not criteria["keywords"]:
        return []

    matches = []
    for doc in drive_dir.glob("*.md"):
        name_lower = doc.stem.lower().replace("-", " ").replace("_", " ")
        for kw in criteria["keywords"]:
            if kw.lower() in name_lower:
                # Derive a display name from the filename
                display = doc.stem.replace("-", " ")
                matches.append({
                    "filename": doc.stem,
                    "display": display,
                    "path": f"Drive/{doc.stem}",
                })
                break

    return matches


def scan_meetings(vault: Path, criteria: dict, days: int = 14) -> list[dict]:
    """Scan recent meeting filenames for keyword matches. Uses CLI when available."""
    if not criteria["keywords"]:
        return []

    today = date.today()
    cutoff = today - timedelta(days=days)
    matches = []
    matched_files = set()

    # --- CLI-accelerated path ---
    if CLI_AVAILABLE:
        year_str = str(today.year)
        for kw in criteria["keywords"]:
            results = cli_search(f"file:{kw}", f"Meetings/{year_str}/")
            for r in results:
                file_path = r.get("path", r.get("file", ""))
                if not file_path or file_path in matched_files:
                    continue
                # Extract date from filename (YYYY-MM-DD prefix)
                stem = Path(file_path).stem
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", stem)
                if date_match:
                    try:
                        file_date = date.fromisoformat(date_match.group(1))
                        if file_date < cutoff:
                            continue
                    except ValueError:
                        continue
                matched_files.add(file_path)
                display = stem.replace("-", " ")
                display = re.sub(r"^\d{4}\s*\d{2}\s*\d{2}\s*", "", display).strip()
                path_no_ext = file_path.replace(".md", "") if file_path.endswith(".md") else file_path
                matches.append({
                    "filename": stem,
                    "display": display,
                    "path": path_no_ext,
                    "date": date_match.group(1) if date_match else "",
                })
        return matches

    # --- File-based fallback ---
    for delta in range(days):
        d = today - timedelta(days=delta)
        month_str = f"{d.month:02d}-{MONTH_NAMES[d.month]}"
        day_name = d.strftime("%A")
        day_str = f"{d.day:02d}-{day_name}"
        day_dir = vault / "Meetings" / str(d.year) / month_str / day_str

        if not day_dir.exists():
            continue

        for meeting_file in day_dir.glob("*.md"):
            name_lower = meeting_file.stem.lower().replace("-", " ")
            for kw in criteria["keywords"]:
                if kw.lower() in name_lower:
                    rel_path = meeting_file.relative_to(vault)
                    display = meeting_file.stem.replace("-", " ")
                    # Strip leading date prefix if present
                    display = re.sub(r"^\d{4}\s*\d{2}\s*\d{2}\s*", "", display).strip()
                    matches.append({
                        "filename": meeting_file.stem,
                        "display": display,
                        "path": str(rel_path).replace(".md", ""),
                        "date": d.isoformat(),
                    })
                    break

    return matches


def truncate(s: str, maxlen: int = 60) -> str:
    """Truncate a string with ... if too long."""
    if len(s) <= maxlen:
        return s
    return s[:maxlen - 3] + "..."


def build_related_items_section(
    jira_matches: list[dict],
    pr_matches: list[dict],
    drive_matches: list[dict],
    meeting_matches: list[dict],
    today_str: str,
) -> str:
    """Generate the ## Related Items markdown section."""
    lines = [
        "## Related Items",
        "",
        f"> [!info] Auto-generated by /project-sync on {today_str}. Do not edit manually.",
        "",
    ]

    if jira_matches:
        lines.append("### JIRA Issues")
        lines.append("| Key | Summary | Status |")
        lines.append("|-----|---------|--------|")
        for m in jira_matches:
            key = m["key"]
            summary = truncate(m["summary"])
            status = m["status"]
            lines.append(f"| [[{m['path']}\\|{key}]] | {summary} | {status} |")
        lines.append("")

    if pr_matches:
        lines.append("### Pull Requests")
        lines.append("| PR | Title | Status |")
        lines.append("|----|-------|--------|")
        for m in pr_matches:
            display = m["display"]
            title = truncate(m["title"])
            status = m["status"]
            lines.append(f"| [[{m['path']}\\|{display}]] | {title} | {status} |")
        lines.append("")

    if drive_matches:
        lines.append("### Documents")
        for m in drive_matches:
            lines.append(f"- [[{m['path']}\\|{m['display']}]]")
        lines.append("")

    if meeting_matches:
        lines.append("### Recent Meetings")
        for m in meeting_matches:
            lines.append(f"- [[{m['path']}\\|{m['display']}]]")
        lines.append("")

    if not any([jira_matches, pr_matches, drive_matches, meeting_matches]):
        lines.append("No related items found. Consider adding `keywords:` to this note's frontmatter.")
        lines.append("")

    return "\n".join(lines)


def update_project_note(note_path: Path, section: str):
    """Replace or append ## Related Items section in the project note."""
    text = note_path.read_text(encoding="utf-8")

    # Find ## Related Items heading
    pattern = re.compile(r"^## Related Items\s*$", re.MULTILINE)
    match = pattern.search(text)

    if match:
        start = match.start()
        # Find the next ## heading after Related Items (or EOF)
        rest = text[match.end():]
        next_heading = re.search(r"^## ", rest, re.MULTILINE)
        if next_heading:
            end = match.end() + next_heading.start()
        else:
            end = len(text)
        new_text = text[:start].rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"
        if next_heading:
            new_text += "\n" + text[end:]
    else:
        # Append at end
        new_text = text.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"

    note_path.write_text(new_text, encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print("Usage: project_sync.py <vault-path>", file=sys.stderr)
        sys.exit(1)

    vault = Path(sys.argv[1])
    if not vault.exists():
        print(f"Error: Vault path not found: {vault}", file=sys.stderr)
        sys.exit(1)

    today_str = date.today().isoformat()

    if CLI_AVAILABLE:
        print("Obsidian CLI detected — using CLI-accelerated search")
    else:
        print("Obsidian CLI not found — using file-based search")

    print("Parsing Work Pipeline...")
    projects = parse_work_pipeline(vault)
    print(f"  Found {len(projects)} active projects")

    for proj in projects:
        name = proj["name"]
        note_path = proj["path"]

        if not note_path or not note_path.exists():
            print(f"\n⚠ {name}: project file not found, skipping")
            continue

        print(f"\n→ {name}")

        criteria = extract_match_criteria(note_path, name)
        jira_keys_str = ", ".join(sorted(criteria["jira_keys"])[:5])
        kw_str = ", ".join(criteria["keywords"][:5])
        print(f"  JIRA keys: {jira_keys_str or '(none)'}")
        print(f"  Keywords: {kw_str or '(none)'}")

        jira_matches = scan_jira(vault, criteria)
        pr_matches = scan_prs(vault, criteria)
        drive_matches = scan_drive(vault, criteria)
        meeting_matches = scan_meetings(vault, criteria)

        total = len(jira_matches) + len(pr_matches) + len(drive_matches) + len(meeting_matches)
        print(f"  Matches: {len(jira_matches)} JIRA, {len(pr_matches)} PRs, "
              f"{len(drive_matches)} Drive, {len(meeting_matches)} Meetings (total: {total})")

        section = build_related_items_section(
            jira_matches, pr_matches, drive_matches, meeting_matches, today_str
        )
        update_project_note(note_path, section)
        print(f"  ✓ Updated {note_path.name}")

    print(f"\n✅ Project sync complete ({len(projects)} projects)")


if __name__ == "__main__":
    main()
