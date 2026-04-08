#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Sync GitHub PRs to Obsidian as separate Base notes.

JIRA syncing has been moved to pkm-sync (jira_work source), which runs as part
of `pkm-sync sync --since 1d` in step 2 of sync_all_sources.sh.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any


def run_command(cmd: List[str]) -> Any:
    """Run a command and return JSON output."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout:
            return json.loads(result.stdout)
        return {}
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}", file=sys.stderr)
        print(f"Error: {e.stderr}", file=sys.stderr)
        return {}
    except json.JSONDecodeError:
        print(f"Error parsing JSON from command: {' '.join(cmd)}", file=sys.stderr)
        return {}


def check_pr_comments(repo: str, pr_number: int) -> bool:
    """Check if there are unanswered comments on a PR."""
    try:
        result = subprocess.run(
            ['gh', 'pr', 'view', str(pr_number), '-R', repo, '--json', 'comments'],
            capture_output=True,
            text=True,
            check=True
        )

        if not result.stdout:
            return False

        data = json.loads(result.stdout)
        comments = data.get('comments', [])

        if not comments:
            return False

        user_result = subprocess.run(
            ['gh', 'api', 'user', '--jq', '.login'],
            capture_output=True,
            text=True,
            check=True
        )
        current_user = user_result.stdout.strip()

        last_comment = comments[-1]
        return last_comment.get('author', {}).get('login', '') != current_user

    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return False


def check_pr_ci_status(repo: str, pr_number: int) -> Dict[str, Any]:
    """Check CI status for a PR."""
    try:
        result = subprocess.run(
            ['gh', 'pr', 'checks', str(pr_number), '-R', repo, '--json', 'state,name'],
            capture_output=True,
            text=True,
            check=True
        )

        if not result.stdout:
            return {'has_checks': False, 'failed': False, 'pending': False}

        checks = json.loads(result.stdout)

        if not checks:
            return {'has_checks': False, 'failed': False, 'pending': False}

        has_failed = any(check.get('state') == 'FAILURE' for check in checks)
        has_pending = any(check.get('state') == 'PENDING' for check in checks)

        return {
            'has_checks': True,
            'failed': has_failed,
            'pending': has_pending,
            'total_checks': len(checks)
        }

    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {'has_checks': False, 'failed': False, 'pending': False}


def get_github_prs() -> List[Dict[str, Any]]:
    """Query GitHub for open PRs authored by current user."""

    prs = run_command([
        'gh', 'search', 'prs',
        '--author=@me',
        '--state=open',
        '--json', 'number,title,repository,url,createdAt,updatedAt,isDraft',
        '--limit', '100'
    ])

    if not isinstance(prs, list):
        return []

    pr_list = []
    for pr in prs:
        repo = pr['repository']['nameWithOwner']
        repo_owner, repo_name = repo.split('/')

        gh_user = os.environ.get("GITHUB_USER", "")
        category = 'personal' if (gh_user and gh_user == repo_owner) else 'work'
        if 'CLAUDE.md' in pr['title'] or 'Add CLAUDE.md' in pr['title']:
            category = 'documentation'

        print(f"   Checking comments on {repo_name}#{pr['number']}...", file=sys.stderr)
        has_unanswered = check_pr_comments(repo, pr['number'])

        print(f"   Checking CI status on {repo_name}#{pr['number']}...", file=sys.stderr)
        ci_status = check_pr_ci_status(repo, pr['number'])

        pr_list.append({
            'number': pr['number'],
            'title': pr['title'],
            'repo_owner': repo_owner,
            'repo_name': repo_name,
            'repo_full': repo,
            'url': pr['url'],
            'created': pr['createdAt'],
            'updated': pr['updatedAt'],
            'draft': pr.get('isDraft', False),
            'category': category,
            'has_unanswered_comments': has_unanswered,
            'ci_failed': ci_status.get('failed', False),
            'ci_pending': ci_status.get('pending', False),
            'ci_total_checks': ci_status.get('total_checks', 0),
        })

    return pr_list


def create_pr_note(pr: Dict[str, Any], pr_dir: Path) -> Path:
    """Create or update a GitHub PR note."""

    filename = f"{pr['repo_name']}-{pr['number']}.md"
    note_path = pr_dir / filename

    created_date = pr['created'][:10]
    updated_date = pr['updated'][:10]

    frontmatter = {
        'number': pr['number'],
        'title': pr['title'],
        'repo': pr['repo_full'],
        'repo_name': pr['repo_name'],
        'repo_owner': pr['repo_owner'],
        'url': pr['url'],
        'created': created_date,
        'updated': updated_date,
        'draft': pr['draft'],
        'category': pr['category'],
        'has_unanswered_comments': pr.get('has_unanswered_comments', False),
        'ci_failed': pr.get('ci_failed', False),
        'ci_pending': pr.get('ci_pending', False),
        'ci_total_checks': pr.get('ci_total_checks', 0),
        'source': 'github',
    }

    content = "---\n"
    for key, value in frontmatter.items():
        if isinstance(value, bool):
            content += f'{key}: {str(value).lower()}\n'
        elif isinstance(value, (int, float)):
            content += f'{key}: {value}\n'
        elif value:
            if isinstance(value, str) and '"' in value:
                value = value.replace('"', '\\"')
            content += f'{key}: "{value}"\n'
    content += "---\n\n"
    content += f"# [{pr['repo_name']}#{pr['number']}: {pr['title']}]({pr['url']})\n\n"
    repo_url = f"https://github.com/{pr['repo_full']}"
    content += f"**Repository:** [{pr['repo_full']}]({repo_url})  \n"
    content += f"**Status:** {'Draft' if pr['draft'] else 'Open'}  \n"
    content += f"**Updated:** {updated_date}  \n"

    attention_items = []
    if pr.get('has_unanswered_comments'):
        attention_items.append("💬 Has unanswered comments")
    if pr.get('ci_failed'):
        attention_items.append("❌ CI checks failed")
    elif pr.get('ci_pending'):
        attention_items.append("⏳ CI checks pending")

    if attention_items:
        content += f"\n**Needs Attention:**  \n"
        for item in attention_items:
            content += f"- {item}  \n"

    if pr.get('ci_total_checks', 0) > 0:
        content += f"\n**CI Checks:** {pr['ci_total_checks']} total  \n"

    content += f"\n[View PR on GitHub]({pr['url']})\n"

    note_path.write_text(content)
    return note_path


def clean_old_pr_notes(pr_dir: Path, current_keys: set):
    """Remove notes for PRs that are no longer open."""
    if not pr_dir.exists():
        return

    for note_path in pr_dir.glob("*.md"):
        if note_path.stem not in current_keys:
            note_path.unlink()
            print(f"   Removed closed/stale: {note_path.name}")


def main():
    """Main function to sync GitHub PRs to Obsidian Base notes."""

    if len(sys.argv) < 2:
        print("Usage: sync_daily_work.py <vault-path>", file=sys.stderr)
        sys.exit(1)

    vault_path = Path(sys.argv[1])

    if not vault_path.exists():
        print(f"Error: Vault path not found: {vault_path}", file=sys.stderr)
        sys.exit(1)

    pr_dir = vault_path / "prs"
    pr_dir.mkdir(exist_ok=True)

    print("Querying GitHub PRs...")
    github_prs = get_github_prs()

    print("\nCreating GitHub PR notes...")
    pr_keys = set()
    for pr in github_prs:
        create_pr_note(pr, pr_dir)
        pr_key = f"{pr['repo_name']}-{pr['number']}"
        pr_keys.add(pr_key)
        print(f"   ✓ {pr['repo_name']}#{pr['number']}")

    print("\nCleaning up closed PRs...")
    clean_old_pr_notes(pr_dir, pr_keys)

    print(f"\n✅ Sync complete!")
    print(f"   - {len(github_prs)} GitHub PRs in {pr_dir}")
    print(f"\n💡 Use Obsidian Bases to view and filter these notes!")


if __name__ == '__main__':
    main()
