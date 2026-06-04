#!/usr/bin/env python3
"""Test run on first 3 people."""

import json
import os
import re
from datetime import datetime
from collections import defaultdict

VAULT_ROOT = os.environ.get("VAULT_DIR", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TODAY = "2026-04-13"
DAYS_LOOKBACK = 30

def load_json(path):
    with open(path) as f:
        return json.load(f)

def read_page(page_path):
    full = os.path.join(VAULT_ROOT, page_path)
    if not os.path.exists(full):
        return None
    with open(full, encoding='utf-8') as f:
        return f.read()

def channel_to_team(channels):
    teams = []
    seen = set()
    channel_set = set(channels)
    if any('hypershift' in c or ('hcp' in c and 'log' not in c) for c in channel_set):
        t = 'HyperShift / Hosted Control Planes'
        if t not in seen:
            teams.append(t)
            seen.add(t)
    if any('rosa' in c for c in channel_set):
        t = 'ROSA'
        if t not in seen:
            teams.append(t)
            seen.add(t)
    if any('hcm' in c and 'hcp' not in c for c in channel_set):
        t = 'HCM'
        if t not in seen:
            teams.append(t)
            seen.add(t)
    if any('konflux' in c for c in channel_set):
        t = 'Konflux'
        if t not in seen:
            teams.append(t)
            seen.add(t)
    if any('appsre' in c or 'app-sre' in c for c in channel_set):
        t = 'AppSRE'
        if t not in seen:
            teams.append(t)
            seen.add(t)
    return teams

def format_meeting_link(m):
    path = m.get('path', '')
    title = m.get('title', 'Meeting')
    parts = path.split('/')
    date_label = ''
    if len(parts) >= 4:
        day_part = parts[3]
        month_part = parts[2]
        try:
            day_num = day_part.split('-')[0]
            month_name = month_part.split('-')[1][:3]
            date_label = f'{month_name} {day_num}'
        except:
            date_label = m.get('date', '')
    clean_path = path.replace('.md', '')
    if date_label:
        return f'[[{clean_path}\\|{title} ({date_label})]]'
    else:
        return f'[[{clean_path}\\|{title}]]'

def is_sync_conflict(key):
    return 'sync-conflict' in str(key)

def synthesize_role_section(person):
    fr = person.get('fastrover', {})
    channels = person.get('slack_channels', [])
    if not fr and not channels:
        return 'No role data available.'
    lines = []
    title = fr.get('title', '')
    manager_name = fr.get('manager_name', '')
    manager_page_exists = fr.get('manager_page_exists', False)
    location = fr.get('location', '')
    timezone = fr.get('timezone', '')
    teams = channel_to_team(channels)
    first_line = title if title else 'Unknown Title'
    if teams:
        first_line += f', {" / ".join(teams)}'
    if manager_name:
        if manager_page_exists:
            first_line += f'. Reports to [[{manager_name}]].'
        else:
            first_line += f'. Reports to {manager_name}.'
    lines.append(first_line)
    if location:
        loc_str = location
        if timezone:
            loc_str += f' ({timezone})'
        lines.append(loc_str)
    public_channels = [c for c in channels if not (len(c) > 0 and c[0].isupper() and ' ' in c)]
    if public_channels:
        lines.append(f'Active channels: {", ".join("#" + c for c in public_channels)}')
    return '\n'.join(lines)

def synthesize_current_work(person):
    messages = person.get('slack_messages', [])
    emails = person.get('email_threads', [])
    jiras = person.get('jira_issues', [])
    meetings = person.get('meetings', [])
    daily = person.get('daily_mentions', [])
    clean_jiras = [j for j in jiras if not is_sync_conflict(j['key'])]
    if not messages and not emails and not clean_jiras and not daily:
        return None
    all_text = []
    for m in messages:
        ch = m.get('channel', '')
        if ch and ch[0].isupper() and ' ' in ch:
            continue
        all_text.append(('slack', ch, m.get('content', ''), m.get('date', '')))
    for e in emails:
        all_text.append(('email', '', e.get('subject', ''), e.get('date', '')))
    for d in daily:
        all_text.append(('daily', '', d.get('context', ''), d.get('date', '')))

    theme_keywords = {
        'ROSA HCP control plane upgrades and EOL management': ['upgrade', 'control plane', '4.17', '4.18', 'eol', 'support exception', 'limited support'],
        'HCP control plane log forwarding (NDJSON)': ['log forward', 'ndjson', 'log delivery', 'wg-1080'],
        'BGP / Route Advertisement for ROSA HCP': ['bgp', 'routeadvertisement', 'srccheck', 'eni', 'cannon', 'route'],
        'AMS and RDS database upgrade': ['ams', 'billing', 'rds', 'golang upgrade', 'db size', 'database'],
        'ROSA HCP AWS IAM policy updates': ['rosaku', 'policy', 'aws has just published', 'rosakube', 'iam'],
        'FIPS compliance for ROSA HCP workers': ['fips'],
        'External-ID feature for ROSA clusters': ['external-id', 'external id'],
        'Konflux build migration and architecture': ['konflux', 'pipelines-as-code', 'tekton', 'release pipeline', 'ci-int', 'jenkins'],
        'AppSRE / app-interface operations': ['app-interface', 'appsre', 'incident', 'mr review', 'ambient'],
        'AI / agentic tooling (NIM, goose, NeMo)': ['goose', 'nvidia', 'sandbox', 'nemo', 'agent', 'claude', 'goosetown', 'nim', 'openshell', 'autonomous', 'sub-agent'],
        'IBM & Red Hat partnership': ['ibm', 'ibm cloud', 'ibm & rh', 'ibm and rh'],
        'Regionality demo and feature work': ['regionality', 'region'],
        'Zero Operator Access (ZOA)': ['zero operator access', 'zoa'],
        'TLS 1.3 enablement': ['tls', 'tls1.3', 'tls 1.3'],
        'Contributor PR governance': ['contributor', 'pr', 'unsupported state'],
        'OCPSTRAT / BGP strategy tracking': ['ocpstrat', 'cntrlplane-2805', 'cntrlplane-2806'],
        'HCM outcome refinement': ['hcm outcome', 'refinement', 'hcm refinement', 'bi-weekly hcm'],
    }

    found_themes = {}
    for theme, kws in theme_keywords.items():
        evidence = []
        slack_chans = set()
        date_range = []
        for (src, ch, content, date) in all_text:
            lc = content.lower()
            if any(kw in lc for kw in kws):
                evidence.append((src, ch, date))
                if ch:
                    slack_chans.add(ch)
                if date:
                    date_range.append(date)
        jira_evidence = []
        for j in clean_jiras:
            lc = (j['summary'] + ' ' + j['key']).lower()
            if any(kw in lc for kw in kws):
                jira_evidence.append(j)
        if evidence or jira_evidence:
            found_themes[theme] = {
                'slack_chans': slack_chans,
                'jiras': jira_evidence,
                'evidence': evidence,
                'date_range': sorted(set(date_range))
            }

    bullet_list = []
    for theme, data in found_themes.items():
        evs = data['evidence']
        jiras_t = data['jiras']
        chans = data['slack_chans']
        dates = data['date_range']
        if not evs and not jiras_t:
            continue
        
        # Date range label
        date_label = ''
        if dates:
            try:
                d0 = datetime.strptime(dates[0], '%Y-%m-%d')
                d1 = datetime.strptime(dates[-1], '%Y-%m-%d')
                if d0.month == d1.month:
                    date_label = d0.strftime('%b %Y')
                else:
                    date_label = f'{d0.strftime("%b")}–{d1.strftime("%b %Y")}'
            except:
                date_label = dates[-1] if dates else ''
        
        src_labels = []
        slack_srcs = [e for e in evs if e[0] == 'slack']
        if slack_srcs and chans:
            public_chans = [c for c in sorted(chans) if not (c[0].isupper() and ' ' in c)]
            if public_chans:
                src_labels.append(f'Slack {", ".join("#" + c for c in public_chans)}')
        if jiras_t:
            for j in jiras_t:
                src_labels.append(f'{j["key"]} ({j["status"]})')
        
        action = 'Active in'
        tl = theme.lower()
        if 'upgrade' in tl or 'eol' in tl:
            action = 'Managing'
        elif 'log forward' in tl:
            action = 'Driving'
        elif 'bgp' in tl or 'route' in tl:
            action = 'Coordinating'
        elif 'ams' in tl or 'billing' in tl or 'rds' in tl:
            action = 'Coordinating'
        elif 'konflux' in tl:
            action = 'Participating in'
        elif 'appsre' in tl or 'app-interface' in tl:
            action = 'Leading'
        elif 'ai' in tl or 'agent' in tl:
            action = 'Exploring'
        elif 'ibm' in tl:
            action = 'Engaged in'
        elif 'regionality' in tl:
            action = 'Demoing'
        elif 'zoa' in tl:
            action = 'Refining'
        elif 'fips' in tl:
            action = 'Working on'
        elif 'tls' in tl:
            action = 'Investigating'
        elif 'contributor' in tl:
            action = 'Reviewing'
        elif 'hcm outcome' in tl:
            action = 'Participating in'
        elif any(j.get('role') == 'assignee' for j in jiras_t):
            action = 'Working on'
        
        line = f'- {action} {theme}'
        if src_labels:
            line += f' ({", ".join(src_labels)}'
            if date_label:
                line += f', {date_label}'
            line += ')'
        elif date_label:
            line += f' ({date_label})'
        
        bullet_list.append((len(evs)*1 + len(jiras_t)*3, line))
    
    bullet_list.sort(key=lambda x: -x[0])
    top_bullets = [b[1] for b in bullet_list[:5]]
    return '\n'.join(top_bullets) if top_bullets else None

def synthesize_recent_activity(person, days_lookback):
    messages = person.get('slack_messages', [])
    emails = person.get('email_threads', [])
    meetings = person.get('meetings', [])
    lines = []
    
    public_msgs = [m for m in messages if not (m.get('channel','')[0:1].isupper() and ' ' in m.get('channel',''))]
    if public_msgs:
        chan_counts = defaultdict(int)
        for m in public_msgs:
            chan_counts[m['channel']] += 1
        chan_str = ', '.join(f'#{c}' for c in sorted(chan_counts.keys()))
        lines.append(f'- **Slack ({days_lookback}d):** {len(public_msgs)} messages across {chan_str}')
    
    if emails:
        subjects = [e['subject'] for e in emails[:3]]
        subj_str = ', '.join(f'"{s}"' for s in subjects)
        if len(emails) > 3:
            subj_str += f' (+{len(emails)-3} more)'
        lines.append(f'- **Email ({days_lookback}d):** {len(emails)} threads — {subj_str}')
    
    if meetings:
        clean_meetings = [m for m in meetings if 'sync-conflict' not in m.get('path','') and 'sync-conflict' not in m.get('title','')]
        def meeting_sort_key(m):
            p = m.get('path', '')
            parts = p.split('/')
            if len(parts) >= 4:
                try:
                    year = parts[1]
                    month_num = parts[2].split('-')[0]
                    day_num = parts[3].split('-')[0]
                    return f'{year}{month_num.zfill(2)}{day_num.zfill(2)}'
                except:
                    return p
            return p
        clean_meetings.sort(key=meeting_sort_key, reverse=True)
        top5 = clean_meetings[:5]
        extra = len(clean_meetings) - len(top5)
        meeting_links = [format_meeting_link(m) for m in top5]
        meeting_str = ', '.join(meeting_links)
        if extra > 0:
            meeting_str += f' (+{extra} more)'
        lines.append(f'- **Meetings ({days_lookback}d):** {meeting_str}')
    
    return '\n'.join(lines) if lines else ''

def build_dossier(person, today, days_lookback):
    role = synthesize_role_section(person)
    current_work = synthesize_current_work(person)
    recent = synthesize_recent_activity(person, days_lookback)
    
    parts = []
    parts.append(f'## Dossier\n')
    parts.append(f'> [!info] Auto-generated on {today}\n')
    parts.append(f'### Role & Organization\n{role}\n')
    if current_work:
        parts.append(f'### Current Work\n{current_work}\n')
    if recent:
        parts.append(f'### Recent Activity\n{recent}\n')
    return '\n'.join(parts)

data = load_json(os.path.join(VAULT_ROOT, '.claude/skills/people-dossier/staging/dossier-2026-04-13.json'))
days_lookback = data.get('days_lookback', 30)

# Test on first 3 people
for person in data['people'][:3]:
    name = person['name']
    print(f'\n{"="*60}')
    print(f'PERSON: {name}')
    print('='*60)
    dossier = build_dossier(person, TODAY, days_lookback)
    print(dossier)
