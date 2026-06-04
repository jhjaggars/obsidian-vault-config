---
name: gap-analyzer
description: |
  Analyzes weekly status report emails against the Work Pipeline kanban to find
  untracked initiatives. Produces Projects/Work/Status Report Gap Analysis.md
  with High/Medium/Low Signal gaps, Covered items, and Source Coverage table.
tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash
---

# Gap Analyzer Agent

Compares weekly status report emails (from the pkm-sync vectors DB) against active projects in `Work Pipeline.md` to surface untracked initiatives. Overwrites `Projects/Work/Status Report Gap Analysis.md` on each run.

---

## Step 1: Setup

Get today's date and compute the 5-week lookback window:
```bash
date
python3 -c "from datetime import datetime, timedelta; d=datetime.now()-timedelta(weeks=5); print(d.strftime('%Y-%m-%d'))"
```

Record `TODAY` and `FIVE_WEEKS_AGO` for use in queries.

---

## Step 2: Extract Status Reports from vectors.db

Query the pkm-sync vectors database for recent weekly status emails:
```bash
sqlite3 ~/.config/pkm-sync/vectors.db "
SELECT title, created_at, content FROM documents
WHERE source_type='gmail'
  AND (
    title LIKE '%Weekly Status%'
    OR title LIKE '%SLO Report%'
    OR title LIKE '%weekly report%'
    OR title LIKE '%Status Report%'
    OR title LIKE '%Engineering Update%'
    OR title LIKE '%Eng Update%'
    OR title LIKE '%Weekly Update%'
    OR title LIKE '%Bi-Weekly%'
    OR title LIKE '%Biweekly%'
  )
  AND created_at >= '<FIVE_WEEKS_AGO>'
  AND length(content) > 200
ORDER BY created_at DESC;
" 2>/dev/null
```

Also query the Gmail archive DB for additional coverage:
```bash
sqlite3 ~/.config/pkm-sync/archive.db "
SELECT subject, date_sent, body FROM messages
WHERE (
    subject LIKE '%Weekly Status%'
    OR subject LIKE '%SLO Report%'
    OR subject LIKE '%weekly report%'
    OR subject LIKE '%Status Report%'
    OR subject LIKE '%Engineering Update%'
    OR subject LIKE '%Weekly Update%'
    OR subject LIKE '%Bi-Weekly%'
    OR subject LIKE '%Biweekly%'
  )
  AND date_sent >= '<FIVE_WEEKS_AGO>'
  AND length(body) > 200
ORDER BY date_sent DESC;
" 2>/dev/null
```

Known report series to look for in results (match title/subject keywords):
- ROSA Engineering weekly
- Platform Engineering update
- Virtualization & Modernization update
- GCP HCP weekly
- ARO weekly / ARO HCP
- Ecosystem Infra
- MPEX (Multi-Platform Experience)
- Console SLO Report
- OpenShift Weekly Status
- Hybrid Platforms biweekly
- Konflux status
- HCM / HyperShift engineering

For each report found, record: `{ series, date, title, content_excerpt }`.

If the vectors DB is empty or unavailable, fall back to reading Gmail vault files:
```bash
ls -lt Gmail/*.md 2>/dev/null | head -40
```
Then read the most recent 30 Gmail files and filter for status report content.

---

## Step 3: Read Work Pipeline

Read `Work Pipeline.md`. Parse all sections:
- `## Ideas` — low priority, still track for coverage
- `## Early` — active, primary match target
- `## Mature` — active, primary match target
- `## Complete` — completed, use for "already done" classification

For each item, extract:
- **Project name** (from wiki-link display text, e.g., `Nested Virtualization Support`)
- **JIRA keys** (any `[A-Z]+-\d+` patterns in the line)
- **Match keywords** — derive 2-4 specific keywords from the name:
  - "Nested Virtualization Support" → `["nested virtualization", "nested virt", "nested-virt"]`
  - "OCPSTRAT-2666 BGP ROSA HCP" → `["BGP", "route server", "OCPSTRAT-2666"]`
  - "Zero Operator Access" → `["zero operator access", "ZOA", "operator access"]`
  - "ROSA Regionality" → `["ROSA regionality", "regionality", "ROSA region"]`
  - "Sharded ETCD" → `["sharded etcd", "etcd shard"]`
- **Column** (Ideas/Early/Mature/Complete)

---

## Step 4: Read Active Project Notes

For each project in Early and Mature columns, read its project note:
```
Projects/Work/<ProjectName>.md
```

From each note extract:
- Additional JIRA keys (scan full content for `[A-Z]+-\d+`)
- Status section text (for context)
- Any additional aliases or keywords mentioned in the note

Add these to the project's match keyword set.

---

## Step 5: Analyze and Classify

For each status report found in Step 2, extract named initiatives:

**Extraction approach:** Read through the report content and identify:
1. Named projects, programs, or initiatives (proper nouns, acronyms, product names)
2. JIRA keys mentioned (pattern: `[A-Z]+-\d+`)
3. Risk items, blockers, escalations ("blocked by", "at risk", "dependency on", "waiting on")
4. Cross-team dependencies ("coordination with", "requires", "pending approval from")
5. Milestone references (GA, beta, feature freeze, code freeze, release dates)
6. Recurring themes that appear across multiple reports or series

**Filter out routine noise:**
- On-call rotations and incident response (unless a major incident)
- Minor bug fixes without broader impact
- Hiring/headcount updates (unless severe shortage mentioned)
- Regular ceremony meetings (standups, retros) without notable outcomes
- Generic "team is healthy" status updates
- Individual PTO or absence notices

**For each extracted initiative/topic, classify:**

**Covered** — matches an active project in Work Pipeline (Ideas/Early/Mature) or Complete:
- JIRA key matches exactly
- Keyword match is unambiguous (e.g., "nested virtualization" → Nested Virtualization Support)
- Record which project it maps to

**High Signal** — untracked, high confidence worth adding to pipeline:
- Appears in 2+ different report series (cross-team visibility)
- OR appears in the same series across 3+ consecutive weeks
- OR involves a JIRA key not in any active project note
- OR is a cross-team blocker or major milestone for a tracked project
- OR is a GA/release date milestone for an untracked initiative

**Medium Signal** — untracked, worth monitoring:
- Appears in 1 series across 2+ weeks
- OR single high-stakes event (exec review, customer escalation, regulatory deadline)
- OR appears alongside a tracked JIRA key but represents a separate work stream

**Low Signal** — single notable mention, FYI only:
- Single mention in one report, not obviously noise
- May warrant a pipeline card but needs more signal before acting

---

## Step 6: Write Output

Write (overwrite) `Projects/Work/Status Report Gap Analysis.md` with the following structure:

```markdown
---
created: <TODAY>
updated: <TODAY>
---

# Status Report Gap Analysis

> [!info] Auto-generated by gap-analyzer on <TODAY>. Re-runs every Friday. Do not edit manually — changes will be overwritten.

CORRECT callout format: `> [!info]` (single bracket). INCORRECT: `> [[!info]` (wiki-link syntax, never use).

## High Signal Gaps

*Untracked initiatives with strong evidence (multiple series, multiple weeks, or cross-team blockers). Consider adding to Work Pipeline.*

### <Initiative Name>
- **Appears in:** <Series A> (Week of <date>), <Series B> (Week of <date>)
- **JIRA keys:** <KEY-123>, <KEY-456> (if mentioned)
- **Summary:** Brief description of what the initiative is and why it matters
- **Key quotes:**
  - "<verbatim quote from report>" — <Series>, <date>
  - "<verbatim quote from report>" — <Series>, <date>
- **Suggested pipeline column:** Early / Mature / Ideas

*(repeat for each high signal gap)*

---

## Medium Signal Gaps

*Single-series or single-event items worth monitoring. May warrant a pipeline card.*

### <Initiative Name>
- **Appears in:** <Series> (Weeks of <date1>, <date2>)
- **JIRA keys:** <KEY-123> (if mentioned)
- **Summary:** Brief description
- **Key quote:** "<verbatim quote>" — <Series>, <date>

*(repeat for each medium signal gap)*

---

## Low Signal Gaps

*Single mentions that stood out. FYI — watch for recurrence before adding to pipeline.*

| Initiative | Series | Date | JIRA | Note |
|------------|--------|------|------|------|
| <name> | <series> | <date> | <key or —> | brief note |

---

## Covered by Existing Projects

*These topics from the reports map to tracked projects. Confirms coverage.*

| Topic in Reports | Maps To | Pipeline Column |
|-----------------|---------|----------------|
| <topic> | [[<ProjectName>]] | Early |

---

## Source Coverage

*Which report series were found and their date ranges.*

| Series | Reports Found | Date Range | Notes |
|--------|--------------|------------|-------|
| ROSA Engineering | 4 | <start> – <end> | Weekly cadence |
| Platform Engineering | 2 | <start> – <end> | Biweekly |
| *(series not found)* | 0 | — | Not in DB for this period |

---

## Recommended Pipeline Updates

*Concrete actions based on this analysis:*

1. **Add to Early:** <InitiativeName> — <one sentence rationale>
2. **Add to Ideas:** <InitiativeName> — <one sentence rationale>
3. **Update existing project:** [[<ProjectName>]] — add JIRA key <KEY> found in reports
4. **Watch list:** <InitiativeName> — appeared once, check next week's reports

*Note: This report never modifies `Work Pipeline.md` directly. Apply the above recommendations manually.*
```

**Writing rules:**
- Overwrite the entire file on each run (idempotent)
- Update both `created` and `updated` frontmatter dates
- Omit any section that has zero items (e.g., no Low Signal → omit that section)
- Keep key quotes verbatim but truncate at 120 characters with `...`
- Use wiki-links for project names: `[[Project Name]]`
- Do not link to items outside the vault (no external URLs)
- Sort High Signal gaps by number of appearances (most mentioned first)
- Sort Medium Signal gaps by date (most recent first)

---

## Edge Cases

- **vectors.db unavailable or empty:** Fall back to Gmail vault files. Note in Source Coverage table that DB was unavailable.
- **archive.db unavailable:** Skip, continue with vectors.db only.
- **No status reports found at all:** Write the output file with a note that no reports were found in the lookback window, and list which series were searched.
- **All topics are covered:** Write the file with an empty High/Medium/Low Signal section and a note that all observed initiatives are tracked.
- **Report content is truncated in DB:** Work with what is available; note "content truncated" in Source Coverage for that series.
- **Ambiguous match:** If a topic could map to multiple projects, list it in Covered with all possible matches noted.
- **JIRA key in reports but not in vault:** Surface it in the relevant gap item — this is useful signal for the project-tracker.
