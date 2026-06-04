#!/usr/bin/env python3
"""Synthesize dossier sections for People pages from a staging JSON file."""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_DIR", str(Path(__file__).resolve().parents[2])))
TODAY = "2026-04-14"
JSON_PATH = str(VAULT_ROOT / ".claude/skills/people-dossier/staging/dossier-batch-2026-04-14.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def channel_to_team(channels):
    """Infer team/group from Slack channel membership."""
    channels = channels or []
    ch_str = " ".join(channels)
    labels = []
    if any(c.startswith("team-hcp") or c.startswith("hcp-") for c in channels):
        labels.append("HCP")
    if any("hypershift" in c or "ocp-hypershift" in c for c in channels):
        labels.append("HyperShift / Hosted Control Planes")
    if any("rosa" in c for c in channels):
        labels.append("ROSA")
    if any(c.startswith("hcm-") or c.startswith("team-hcm") for c in channels):
        labels.append("HCM")
    if any("konflux" in c for c in channels):
        labels.append("Konflux")
    return labels


def format_meeting_link(meeting):
    path = meeting.get("path", "")
    title = meeting.get("title", "")
    filename = meeting.get("filename", "")
    # Extract date from path e.g. Meetings/2026/04-April/08-Wednesday/...
    # Try to parse date from path segments
    parts = path.split("/")
    date_display = ""
    try:
        # parts: Meetings / 2026 / 04-April / 08-Wednesday / filename
        month_part = parts[2] if len(parts) > 2 else ""  # e.g. "04-April"
        day_part = parts[3] if len(parts) > 3 else ""     # e.g. "08-Wednesday"
        month_abbr = {"01": "Jan","02": "Feb","03": "Mar","04": "Apr",
                      "05": "May","06": "Jun","07": "Jul","08": "Aug",
                      "09": "Sep","10": "Oct","11": "Nov","12": "Dec"}
        m_num = month_part.split("-")[0] if "-" in month_part else ""
        d_num = day_part.split("-")[0] if "-" in day_part else ""
        m_name = month_abbr.get(m_num, m_num)
        if m_name and d_num:
            date_display = f"{m_name} {d_num.lstrip('0')}"
    except Exception:
        pass

    # Remove the .md suffix from path for wiki-link
    link_path = path.replace(".md", "")
    display = f"{title} ({date_display})" if date_display else title
    return f"[[{link_path}\\|{display}]]"


def synthesize_dossier(person, lookback_days):
    name = person["name"]
    fastrover = person.get("fastrover", {})
    slack_messages = person.get("slack_messages", [])
    slack_channels = person.get("slack_channels", [])
    email_threads = person.get("email_threads", [])
    meetings = person.get("meetings", [])
    jira_issues = person.get("jira_issues", [])
    daily_mentions = person.get("daily_mentions", [])

    # Check if there's any data at all
    has_data = bool(fastrover or slack_messages or email_threads or meetings or jira_issues or daily_mentions)
    if not has_data:
        return f"""## Dossier

> [!info] Auto-generated on {TODAY} — insufficient data to synthesize dossier
"""

    # -----------------------------------------------------------------------
    # Role & Organization
    # -----------------------------------------------------------------------
    role_lines = []
    title = fastrover.get("title", "")
    manager_name = fastrover.get("manager_name", "")
    manager_page_exists = fastrover.get("manager_page_exists", False)
    location = fastrover.get("location", "")
    geo = fastrover.get("geo", "")
    timezone = fastrover.get("timezone", "")

    team_labels = channel_to_team(slack_channels)

    if title or team_labels:
        team_str = ", ".join(team_labels) if team_labels else ""
        if team_str:
            role_line = f"{title}, {team_str}."
        else:
            role_line = f"{title}."
        role_lines.append(role_line)

        if manager_name:
            if manager_page_exists:
                role_lines.append(f"Reports to [[{manager_name}]].")
            else:
                role_lines.append(f"Reports to {manager_name}.")

        # Location — mention if remote/EMEA/non-obvious
        if location and ("Remote" in location or geo == "EMEA" or "APAC" in (geo or "")):
            role_lines.append(f"Location: {location} ({geo}, {timezone}).")
        elif location and location not in ("RH - Sunnyvale - MSO", "RH - Raleigh", "RH - Lowell", "RH - Westford"):
            role_lines.append(f"Location: {location}.")

        if slack_channels:
            ch_str = ", ".join(f"#{c}" for c in slack_channels)
            role_lines.append(f"Active channels: {ch_str}")
    else:
        role_lines.append("No role data available.")

    role_section = "\n".join(role_lines)

    # -----------------------------------------------------------------------
    # Current Work — synthesize from evidence
    # -----------------------------------------------------------------------
    has_work_evidence = bool(slack_messages or email_threads or jira_issues or daily_mentions)
    work_bullets = []

    if has_work_evidence:
        # Collect all text evidence for theme detection
        all_text = []
        for m in slack_messages:
            all_text.append(("slack", m.get("channel",""), m.get("content",""), m.get("date","")))
        for e in email_threads:
            all_text.append(("email", "", e.get("subject",""), e.get("date","")))
        for j in jira_issues:
            # Skip sync-conflict duplicates
            if ".sync-conflict" not in j.get("key",""):
                all_text.append(("jira", "", j.get("summary",""), ""))
        for d in daily_mentions:
            all_text.append(("daily", "", d.get("context",""), d.get("date","")))

        # Theme detection by keywords — build work streams
        themes_found = {}

        # Helper: check if keyword in evidence
        def has_keyword(kws, texts=None):
            if texts is None:
                texts = [t[2] for t in all_text]
            combined = " ".join(texts).lower()
            return any(k.lower() in combined for k in kws)

        def evidence_sources(kws):
            sources = []
            slack_chs = set()
            dates = []
            for src, ch, content, date in all_text:
                if any(k.lower() in content.lower() for k in kws):
                    if src == "slack":
                        slack_chs.add(f"#{ch}")
                        if date:
                            dates.append(date)
                    elif src == "email":
                        sources.append("email")
                        if date:
                            dates.append(date)
                    elif src == "jira":
                        sources.append("Jira")
                    elif src == "daily":
                        if date:
                            dates.append(date)
            if slack_chs:
                sources = [f"Slack {', '.join(sorted(slack_chs))}"] + [s for s in sources if s != "Slack"]
            return sources, dates

        def date_range(dates):
            if not dates:
                return ""
            dates_sorted = sorted(dates)
            if len(dates_sorted) == 1:
                d = dates_sorted[0]
                # Format: Mar 2026
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    return dt.strftime("%b %Y")
                except:
                    return d
            d1, d2 = dates_sorted[0], dates_sorted[-1]
            try:
                dt1 = datetime.strptime(d1, "%Y-%m-%d")
                dt2 = datetime.strptime(d2, "%Y-%m-%d")
                if dt1.month == dt2.month and dt1.year == dt2.year:
                    return dt1.strftime("%b %Y")
                elif dt1.year == dt2.year:
                    return f"{dt1.strftime('%b')}–{dt2.strftime('%b %Y')}"
                else:
                    return f"{dt1.strftime('%b %Y')}–{dt2.strftime('%b %Y')}"
            except:
                return f"{d1}–{d2}"

        # --- Build JIRA reference strings ---
        jira_refs = {}
        for j in jira_issues:
            key = j.get("key","")
            if ".sync-conflict" in key:
                continue
            summary = j.get("summary","")
            status = j.get("status","")
            role = j.get("role","")
            # Check if jira page exists
            jira_page = VAULT_ROOT / "jira" / f"{key}.md"
            if jira_page.exists():
                ref = f"[[jira/{key}\\|{key}]]"
            else:
                ref = key
            jira_refs[key] = {"ref": ref, "summary": summary, "status": status, "role": role}

        # ----------------------------------------------------------------
        # Topic detection — build work stream bullets
        # All text for matching
        all_content = [t[2] for t in all_text]

        # Detect themes based on recurring keywords
        theme_keywords = [
            # (label, keywords, required_count)
            ("HCP control plane log forwarding", ["log forwarding", "log-forwarding", "NDJSON", "ndjson", "wg-1080"], 1),
            ("ROSA HCP upgrade / control plane management", ["control plane upgrade", "upgrade", "EOL", "4.17", "support exception", "upgrade sequencing"], 2),
            ("ROSA HCP AWS IAM / policy management", ["ROSAKubeControllerPolicy", "ROSAControlPlaneOperatorPolicy", "IAM", "iam policy"], 1),
            ("BGP / network routing for ROSA HCP", ["BGP", "bgp", "routeAdvertisement", "cannon", "CNTRLPLANE-2805", "CNTRLPLANE-2806", "OCPSTRAT-2666"], 1),
            ("TLS 1.3 enablement for ROSA fleet", ["TLS 1.3", "tls1.3", "TLS1.3", "TLS"], 1),
            ("External ID feature for ROSA clusters", ["external-ID", "external ID", "external-id"], 1),
            ("FIPS compliance for ROSA HCP", ["FIPS", "fips", "crypto"], 1),
            ("GCP HCP", ["GCP HCP", "gcp hcp", "GCP"], 1),
            ("Regionality / multi-region", ["Regionality", "regionality", "region", "multi-region"], 2),
            ("Zero Operator Access (ZOA)", ["Zero Operator Access", "ZOA", "zoa", "HCMSTRAT-270"], 1),
            ("AMS / billing infrastructure", ["AMS", "billing", "AMS DB", "RDS", "golang"], 2),
            ("Jira Cloud migration", ["Jira Cloud", "jira cloud", "migration", "ranking", "ROSA ranking", "Atlassian"], 2),
            ("ROSA GovCloud", ["GovCloud", "govcloud", "gov cloud"], 1),
            ("Konflux migration / CI/CD", ["konflux", "Konflux", "ci-int", "jenkins", "app-interface", "image build"], 2),
            ("Agentic AI / OpenShell tooling", ["OpenShell", "openShell", "sandbox", "goosetown", "goose", "gastown", "agentic", "Claude Code"], 2),
            ("HCM AppSRE platform operations", ["app-interface", "appsre", "AppSRE", "team-hcm-appsre"], 2),
            ("HCM architecture governance", ["hcm-architecture", "HCM Arch", "business data", "architecture"], 2),
            ("IBM partnership / F2F", ["IBM", "ibm", "IBM & RH", "IBM Cloud"], 2),
            ("HCP log forwarding milestone sync", ["HCP Log Forwarding", "M3 Sync", "log forwarding"], 2),
            ("ROSA Classic capacity reservations", ["capacity reservation", "reservation block", "p5.48xlarge"], 1),
            ("Managed OpenShift interlock / leadership", ["Managed OpenShift Interlock", "managed openshift"], 1),
            ("Hypershift operator / HyperShift engineering", ["HyperShift", "hypershift", "hosted control plane", "hosted-cluster"], 2),
            ("Konflux community / upstream", ["konflux-ci.dev", "Pipelines-as-Code", "Tekton", "konflux community", "KubeCon"], 1),
            ("Platform Engineering", ["Platform Engineering", "platform engineering"], 1),
            ("OpenShift upgrade path", ["upgrade path", "operator upgrade"], 1),
        ]

        # Count which themes appear
        detected_themes = []
        for label, kws, min_count in theme_keywords:
            count = sum(1 for txt in all_content if any(k.lower() in txt.lower() for k in kws))
            if count >= min_count:
                sources, dates = evidence_sources(kws)
                detected_themes.append((label, sources, dates, kws))

        # De-duplicate / merge overlapping themes
        # Build bullets from detected themes (max 5)
        seen_labels = set()
        for label, sources, dates, kws in detected_themes:
            if label in seen_labels:
                continue
            seen_labels.add(label)
            # Find any matching JIRA
            matching_jiras = []
            for key, info in jira_refs.items():
                summary_lower = info["summary"].lower()
                if any(k.lower() in summary_lower for k in kws):
                    matching_jiras.append(info)

            src_str = ""
            if sources:
                src_str = f" ({', '.join(set(sources))}"
                dr = date_range(dates)
                if dr:
                    src_str += f", {dr}"
                src_str += ")"

            jira_str = ""
            if matching_jiras:
                refs = [j["ref"] for j in matching_jiras[:2]]
                jira_str = " " + ", ".join(refs)

            verb = "Working on"
            if "leading" in label.lower() or "management" in label.lower():
                verb = "Leading"
            elif "reviewing" in label.lower():
                verb = "Reviewing"
            elif "participating" in label.lower():
                verb = "Participating in"

            bullet = f"- {verb} {label}{jira_str}{src_str}"
            work_bullets.append(bullet)

            if len(work_bullets) >= 5:
                break

        # If no themes detected but JIRA issues exist, add them directly
        if not work_bullets and jira_refs:
            for key, info in list(jira_refs.items())[:3]:
                role_str = f"({info['role']})" if info["role"] else ""
                bullet = f"- {info['ref']}: {info['summary']} — {info['status']} {role_str}".strip()
                work_bullets.append(bullet)

        # If still nothing and meetings or daily mentions exist
        if not work_bullets and (meetings or daily_mentions):
            # Extract themes from daily mentions
            for dm in daily_mentions[:3]:
                ctx = dm.get("context", "")
                if ctx and len(ctx) > 20:
                    # Truncate to first 120 chars
                    snippet = ctx[:120].strip()
                    if snippet:
                        work_bullets.append(f"- {snippet}…")

    # -----------------------------------------------------------------------
    # Recent Activity
    # -----------------------------------------------------------------------
    activity_lines = []
    nd = f"{lookback_days}d"

    # Slack
    if slack_messages:
        msg_count = len(slack_messages)
        ch_list = []
        seen_ch = set()
        for m in slack_messages:
            ch = m.get("channel","")
            if ch and ch not in seen_ch:
                seen_ch.add(ch)
                ch_list.append(f"#{ch}")
        ch_str = ", ".join(ch_list[:5])
        activity_lines.append(f"- **Slack ({nd}):** {msg_count} messages across {ch_str}")

    # Email
    if email_threads:
        # Deduplicate by subject
        seen_subjects = set()
        unique_threads = []
        for e in email_threads:
            subj = e.get("subject","")
            if subj and subj not in seen_subjects:
                seen_subjects.add(subj)
                unique_threads.append(e)
        if unique_threads:
            # Show up to 3 subjects
            subjects = [f'"{t["subject"][:60]}"' for t in unique_threads[:3]]
            subj_str = ", ".join(subjects)
            activity_lines.append(f"- **Email ({nd}):** {len(unique_threads)} threads — {subj_str}")

    # Meetings — deduplicate by path, take 5 most recent (by path date ordering)
    if meetings:
        # Sort by path (contains date) descending
        def meeting_sort_key(m):
            path = m.get("path","")
            parts = path.split("/")
            try:
                year = parts[1] if len(parts) > 1 else "0000"
                month = parts[2].split("-")[0] if len(parts) > 2 else "00"
                day = parts[3].split("-")[0] if len(parts) > 3 else "00"
                return f"{year}{month}{day.zfill(2)}"
            except:
                return "00000000"

        # Deduplicate by path
        seen_paths = set()
        unique_meetings = []
        for m in meetings:
            p = m.get("path","")
            if p not in seen_paths:
                seen_paths.add(p)
                unique_meetings.append(m)

        sorted_meetings = sorted(unique_meetings, key=meeting_sort_key, reverse=True)
        top5 = sorted_meetings[:5]
        remaining = len(unique_meetings) - len(top5)

        links = [format_meeting_link(m) for m in top5]
        mtg_str = ", ".join(links)
        if remaining > 0:
            mtg_str += f" (+{remaining} more)"
        activity_lines.append(f"- **Meetings ({nd}):** {mtg_str}")

    activity_section = "\n".join(activity_lines) if activity_lines else "_No recent activity recorded._"

    # -----------------------------------------------------------------------
    # Assemble
    # -----------------------------------------------------------------------
    sections = [f"## Dossier\n\n> [!info] Auto-generated on {TODAY}\n\n### Role & Organization\n{role_section}"]

    if work_bullets:
        sections.append(f"### Current Work\n" + "\n".join(work_bullets))

    sections.append(f"### Recent Activity\n{activity_section}")

    return "\n\n".join(sections) + "\n"


def find_dossier_end(content, dossier_start):
    """Find where the dossier section ends (next ## heading or EOF)."""
    # Find next ## heading after the dossier start
    search_from = dossier_start + len("## Dossier")
    next_h2 = content.find("\n## ", search_from)
    if next_h2 == -1:
        return len(content)
    return next_h2  # include the newline before the next heading


def write_dossier(page_path, dossier_content):
    """Write the dossier section to the page. Returns 'created' or 'updated'."""
    full_path = VAULT_ROOT / page_path
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    dossier_marker = "## Dossier"
    idx = content.find(dossier_marker)

    if idx != -1:
        # Replace existing dossier section
        end_idx = find_dossier_end(content, idx)
        new_content = content[:idx] + dossier_content + content[end_idx:]
        action = "updated"
    else:
        # Append at end
        if content and not content.endswith("\n"):
            new_content = content + "\n\n" + dossier_content
        elif content and not content.endswith("\n\n"):
            new_content = content + "\n" + dossier_content
        else:
            new_content = content + dossier_content
        action = "created"

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return action


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    lookback_days = data.get("days_lookback", 30)
    people = data.get("people", [])

    if not people:
        print("WARNING: No people found in JSON file.")
        return

    stats = {"processed": 0, "created": 0, "updated": 0, "skipped": 0}

    for person in people:
        name = person.get("name", "Unknown")
        page_path = person.get("page_path", "")

        if not page_path:
            print(f"SKIP {name}: No page_path")
            stats["skipped"] += 1
            continue

        full_path = VAULT_ROOT / page_path
        if not full_path.exists():
            print(f"SKIP {name}: People page not found ({page_path})")
            stats["skipped"] += 1
            continue

        try:
            dossier = synthesize_dossier(person, lookback_days)
            action = write_dossier(page_path, dossier)
            stats["processed"] += 1
            if action == "created":
                stats["created"] += 1
            else:
                stats["updated"] += 1
            print(f"OK [{action}] {name}")
        except Exception as e:
            print(f"ERROR {name}: {e}")
            stats["skipped"] += 1

    print(f"""
Dossier synthesis complete:
  - {stats['processed']} people processed
  - {stats['created']} dossiers created (new)
  - {stats['updated']} dossiers updated (replaced existing)
  - {stats['skipped']} skipped (page not found or no data)
""")


if __name__ == "__main__":
    main()
