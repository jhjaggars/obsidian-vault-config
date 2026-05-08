import os
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path


def _find_vault_root() -> str:
    """Walk up from this script's location to find the vault root (has .obsidian/)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".obsidian").is_dir():
            return str(parent)
    raise RuntimeError(f"Could not find vault root (no .obsidian/ dir above {__file__})")


VAULT_DIR = os.environ.get("VAULT_DIR") or _find_vault_root()

ALLOWED_BASH_PREFIXES = [
    "pkm-sync",
    "sqlite3",
    "grep",
    f"python3 {VAULT_DIR}/.claude/skills/daily-sync-all/scripts/jira_deadlines.py",
    "python3 .claude/skills/daily-sync-all/scripts/jira_deadlines.py",
    "date",
    "ls",
    "jira issue view",
    "jira issue list",
]

if not os.environ.get("DISABLE_OBSIDIAN_CLI"):
    ALLOWED_BASH_PREFIXES.insert(0, "obsidian")
    ALLOWED_BASH_PREFIXES.insert(1, "/Applications/Obsidian.app/Contents/MacOS/obsidian")


def bash(command: str, timeout: int = 60) -> str:
    cmd = os.path.expanduser(command.lstrip())
    if not any(cmd.startswith(prefix) for prefix in ALLOWED_BASH_PREFIXES):
        return f"Error: command not allowed: {command[:60]}"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


DEFAULT_READ_LIMIT = 100  # lines; agent must explicitly request more


def read(file_path: str, offset: int = None, limit: int = None) -> str:
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except Exception as e:
        return f"Error: {e}"

    total_lines = len(lines)
    start = (offset - 1) if offset else 0
    effective_limit = limit if limit is not None else DEFAULT_READ_LIMIT
    end = start + effective_limit
    truncated = end < total_lines
    lines = lines[start:end]
    first_line_num = start + 1

    numbered = []
    for i, line in enumerate(lines, start=first_line_num):
        numbered.append(f"  {i}\t{line.rstrip()}")
    result = "\n".join(numbered)
    if truncated:
        result += f"\n[... truncated: showed lines {first_line_num}-{end} of {total_lines} total. Use offset/limit to read more.]"
    return result


def write(file_path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        return f"Written: {file_path}"
    except Exception as e:
        return f"Error: {e}"


def edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    try:
        with open(file_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except Exception as e:
        return f"Error: {e}"

    count = content.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if not replace_all and count != 1:
        return f"Error: old_string found {count} times in {file_path} (expected exactly 1; use replace_all=True for multiple)"

    content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
    with open(file_path, "w") as f:
        f.write(content)
    return f"Edited: {file_path}"


def glob(pattern: str, path: str = None) -> str:
    base = Path(path or VAULT_DIR)
    if pattern.startswith("**"):
        matches = sorted(str(p) for p in base.rglob(pattern.removeprefix("**/")))
    else:
        matches = sorted(str(p) for p in base.glob(pattern))
    return "\n".join(matches) if matches else "No matches found"


def replace_section(file_path: str, section: str, content: str) -> str:
    """Replace content between %% section:<name> %% and %% /section:<name> %% markers."""
    try:
        with open(file_path, "r") as f:
            text = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except Exception as e:
        return f"Error: {e}"

    open_marker = f"%% section:{section} %%"
    close_marker = f"%% /section:{section} %%"

    open_idx = text.find(open_marker)
    close_idx = text.find(close_marker)

    if open_idx == -1:
        return f"Error: section marker '{open_marker}' not found in {file_path}"
    if close_idx == -1:
        return f"Error: closing marker '{close_marker}' not found in {file_path}"
    if close_idx < open_idx:
        return f"Error: closing marker appears before opening marker in {file_path}"

    new_text = text[:open_idx] + open_marker + "\n" + content + "\n" + text[close_idx:]
    with open(file_path, "w") as f:
        f.write(new_text)
    return f"Replaced section '{section}' in {file_path}"


def grep(pattern: str, path: str = None, include: str = None) -> str:
    base = path or VAULT_DIR
    results = []
    for root, _, files in os.walk(base):
        for fname in files:
            if include and not fnmatch(fname, include):
                continue
            filepath = os.path.join(root, fname)
            try:
                with open(filepath, "r", errors="ignore") as f:
                    for linenum, line in enumerate(f, 1):
                        if re.search(pattern, line):
                            results.append(f"{filepath}:{linenum}: {line.rstrip()}")
                            if len(results) >= 200:
                                return "\n".join(results)
            except (OSError, UnicodeDecodeError):
                continue
    return "\n".join(results) if results else "No matches found"
