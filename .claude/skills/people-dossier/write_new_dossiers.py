#!/usr/bin/env python3
# /// script
# dependencies = []
# ///
"""Write dossiers for people who don't have one yet, from the batch JSON."""

import json
import os
import pathlib
from datetime import datetime

VAULT = pathlib.Path(os.environ.get("VAULT_DIR", str(pathlib.Path(__file__).resolve().parents[3])))
JSON_PATH = VAULT / ".claude/skills/people-dossier/staging/dossier-batch-2026-04-14.json"
TODAY = "2026-04-14"
LOOKBACK = 30


def month_abbr(m):
    return ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][int(m)]


def fmt_meeting_link(m):
    path = m.get("path", "")
    title = m.get("title", "")
    parts = path.replace(".md","").split("/")
    try:
        m_num = parts[2].split("-")[0] if len(parts) > 2 else ""
        d_num = parts[3].split("-")[0] if len(parts) > 3 else ""
        mon = month_abbr(m_num) if m_num else ""
        d_clean = d_num.lstrip("0") if d_num else ""
        date_str = f"{mon} {d_clean}" if mon and d_clean else ""
    except Exception:
        date_str = ""
    link_path = path.replace(".md","")
    display = f"{title} ({date_str})" if date_str else title
    return f"[[{link_path}\\|{display}]]"


def date_range(dates):
    dates = [d for d in dates if d]
    if not dates:
        return ""
    ds = sorted(dates)
    try:
        d1 = datetime.strptime(ds[0], "%Y-%m-%d")
        d2 = datetime.strptime(ds[-1], "%Y-%m-%d")
        if d1.month == d2.month and d1.year == d2.year:
            return d1.strftime("%b %Y")
        elif d1.year == d2.year:
            return f"{d1.strftime('%b')}\u2013{d2.strftime('%b %Y')}"
        return f"{d1.strftime('%b %Y')}\u2013{d2.strftime('%b %Y')}"
    except Exception:
        return ds[-1]


def infer_team(channels):
    labels = []
    seen = set()
    def add(l):
        if l not in seen:
            seen.add(l)
            labels.append(l)
    for c in (channels or []):
        if "hypershift" in c or "ocp-hypershift" in c:
            add("HyperShift / Hosted Control Planes")
        if c.startswith("team-hcp") or c.startswith("hcp-"):
            add("HCP")
        if "rosa" in c:
            add("ROSA")
        if c.startswith("hcm-") or c.startswith("team-hcm"):
            add("HCM")
        if "konflux" in c:
            add("Konflux")
        if "aro" in c:
            add("ARO")
        if "ome" in c:
            add("OME")
    return labels


def synth(p):
    fr = p.get("fastrover", {})
    msgs = p.get("slack_messages", [])
    chs = p.get("slack_channels", [])
    emails = p.get("email_threads", [])
    meetings = p.get("meetings", [])
    jiras = [j for j in p.get("jira_issues", []) if ".sync-conflict" not in j.get("key","")]
    mentions = p.get("daily_mentions", [])

    has_data = bool(fr or msgs or emails or meetings or jiras or mentions)
    if not has_data:
        return f"## Dossier\n\n> [!info] Auto-generated on {TODAY} \u2014 insufficient data to synthesize dossier\n"

    # Role section
    title = fr.get("title","")
    mgr = fr.get("manager_name","")
    mgr_exists = fr.get("manager_page_exists", False)
    loc = fr.get("location","")
    geo = fr.get("geo","")
    tz = fr.get("timezone","")
    teams = infer_team(chs)

    role_lines = []
    team_str = ", ".join(teams) if teams else ""
    if title and team_str:
        role_lines.append(f"{title}, {team_str}.")
    elif title:
        role_lines.append(f"{title}.")
    else:
        role_lines.append("No role data available.")

    if mgr:
        role_lines.append(f"Reports to [[{mgr}]]." if mgr_exists else f"Reports to {mgr}.")

    if loc and ("Remote" in loc or geo in ("EMEA","APAC")):
        role_lines.append(f"Location: {loc} ({geo}, {tz}).")

    if chs:
        role_lines.append("Active channels: " + ", ".join(f"#{c}" for c in chs))

    role_section = "\n".join(role_lines)

    # Current Work
    all_content = (
        [m.get("content","") for m in msgs] +
        [e.get("subject","") for e in emails] +
        [j.get("summary","") for j in jiras] +
        [d.get("context","") for d in mentions]
    )
    combined = " ".join(all_content).lower()
    all_dates = [m.get("date","") for m in msgs] + [e.get("date","") for e in emails]

    work_bullets = []

    def kw(*words):
        return any(w in combined for w in words)

    def ch_match(*words):
        return [f"#{c}" for c in chs if any(w in c for w in words)]

    if kw("hypershift","hosted control plane","hosted-cluster","hostedcluster"):
        dr = date_range(all_dates)
        src = ", ".join(ch_match("hypershift","hcp")) or "Slack"
        work_bullets.append(f"- Working on HyperShift / Hosted Control Planes engineering ({src}, {dr})")

    if kw("rosa") and not any("hypershift" in b for b in work_bullets):
        dr = date_range(all_dates)
        src = ", ".join(ch_match("rosa")) or "Slack"
        work_bullets.append(f"- Working on ROSA platform ({src}, {dr})")

    if kw("konflux","tekton","pipelines-as-code","pipeline-as-code"):
        dr = date_range(all_dates)
        src = ", ".join(ch_match("konflux")) or "Slack"
        work_bullets.append(f"- Participating in Konflux CI/CD community ({src}, {dr})")

    if kw("aro") and "external-wg-aro" in " ".join(chs):
        dr = date_range(all_dates)
        src = ", ".join(ch_match("aro")) or "Slack"
        work_bullets.append(f"- Working on ARO (Azure Red Hat OpenShift) release engineering ({src}, {dr})")

    if kw("openshift ai","rhoai","kagent","mlflow","llm","model serving") and not work_bullets:
        dr = date_range(all_dates)
        work_bullets.append(f"- Engaged with OpenShift AI / ML platform (Slack, {dr})")

    if kw("upgrade","eol","4.17","control plane upgrade") and not work_bullets:
        dr = date_range(all_dates)
        work_bullets.append(f"- Working on cluster/control plane upgrade coordination ({dr})")

    # Add JIRA items
    for j in jiras[:2]:
        key = j["key"]
        summary = j["summary"]
        status = j["status"]
        jira_page = VAULT / "jira" / f"{key}.md"
        ref = f"[[jira/{key}\\|{key}]]" if jira_page.exists() else key
        work_bullets.append(f"- Working on {ref}: {summary} ({status})")

    # Fallback to daily mentions
    if not work_bullets and mentions:
        for dm in mentions[:2]:
            ctx = dm.get("context","")
            if len(ctx) > 30:
                work_bullets.append(f"- {ctx[:120].strip()}\u2026")

    # Recent Activity
    activity = []
    nd = f"{LOOKBACK}d"
    if msgs:
        unique_chs = []
        seen_chs = set()
        for m in msgs:
            c = m.get("channel","")
            if c and c not in seen_chs:
                seen_chs.add(c)
                unique_chs.append(f"#{c}")
        activity.append(f"- **Slack ({nd}):** {len(msgs)} messages across {', '.join(unique_chs[:5])}")

    if emails:
        seen_s = set()
        uniq_emails = []
        for e in emails:
            s = e.get("subject","")
            if s and s not in seen_s:
                seen_s.add(s)
                uniq_emails.append(e)
        subjs = [f'"{e["subject"][:60]}"' for e in uniq_emails[:3]]
        activity.append(f"- **Email ({nd}):** {len(uniq_emails)} threads \u2014 {', '.join(subjs)}")

    if meetings:
        seen_paths = set()
        unique_mtgs = []
        for m in meetings:
            if m.get("path","") not in seen_paths:
                seen_paths.add(m["path"])
                unique_mtgs.append(m)

        def sort_key(m):
            parts = m["path"].split("/")
            try:
                return f"{parts[1]}{parts[2].split('-')[0].zfill(2)}{parts[3].split('-')[0].zfill(2)}"
            except Exception:
                return "000000"

        sorted_mtgs = sorted(unique_mtgs, key=sort_key, reverse=True)
        top5 = sorted_mtgs[:5]
        extra = len(unique_mtgs) - len(top5)
        links = [fmt_meeting_link(m) for m in top5]
        mtg_str = ", ".join(links)
        if extra > 0:
            mtg_str += f" (+{extra} more)"
        activity.append(f"- **Meetings ({nd}):** {mtg_str}")

    act_str = "\n".join(activity) if activity else "_No recent activity recorded._"

    sections = [
        f"## Dossier\n\n> [!info] Auto-generated on {TODAY}\n\n### Role & Organization\n{role_section}"
    ]
    if work_bullets:
        sections.append("### Current Work\n" + "\n".join(work_bullets))
    sections.append(f"### Recent Activity\n{act_str}")
    return "\n\n".join(sections) + "\n"


def main():
    with open(JSON_PATH) as f:
        data = json.load(f)

    in_json = {p["name"]: p for p in data["people"]}

    created = 0
    skipped = 0

    for page in sorted((VAULT / "People").glob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        if "## Dossier" in text:
            continue

        name = page.stem
        if name not in in_json:
            print(f"SKIP (not in JSON): {name}")
            skipped += 1
            continue

        person = in_json[name]
        dossier = synth(person)

        sep = "\n\n" if text and not text.endswith("\n\n") else ("\n" if text and not text.endswith("\n") else "")
        new_text = text + sep + dossier
        page.write_text(new_text, encoding="utf-8")
        print(f"CREATED: {name}")
        created += 1

    print(f"\nSummary: {created} created, {skipped} skipped (not in JSON)")


if __name__ == "__main__":
    main()
