---
name: conversation-summarizer
description: |
  Summarizes today's conversations (Slack DMs, group DMs, threads, and email)
  into a ### Conversations section in the daily note. Reads extracted JSON from
  the extraction script and generates concise 1-line summaries per person.
tools:
  - Read
  - Edit
  - Glob
  - Bash
---

# Conversation Summarizer Agent

Reads today's extracted conversations JSON and writes a concise `### Conversations` section into the daily note.

The prompt will include the path to the JSON file, e.g.:
> Summarize conversations from /path/to/conversations-YYYY-MM-DD.json into today's daily note.

---

## Step 1: Setup

Get today's date:
```bash
date '+%Y-%m-%d %H:%M'
```

Find today's daily note. Try the CLI first:
```bash
timeout 10 /Applications/Obsidian.app/Contents/MacOS/obsidian daily:path 2>/dev/null
```
If that fails, compute the path manually:
- Pattern: `daily/YYYY/MM-MonthName/YYYY-MM-DD-DayName.md`
- Example: `daily/2026/04-April/2026-04-06-Monday.md`

Read the daily note to understand its current structure.

---

## Step 2: Read Conversations JSON

Read the JSON file from the path given in the prompt. The structure is:

```json
{
  "date": "2026-04-06",
  "conversations": [
    {
      "type": "dm",
      "person": "James Laska",
      "message_count": 48,
      "messages": [{"author": "...", "content": "...", "time": "..."}]
    },
    {
      "type": "mpdm",
      "channel": "mpdm-jjaggars--scuppett-1",
      "participants": ["Stephen Cuppett"],
      "message_count": 8,
      "messages": [...]
    },
    {
      "type": "thread",
      "channel": "team-ocp-hypershift",
      "participants": ["Bryan Cox", "Adam Miller"],
      "message_count": 16,
      "messages": [...]
    },
    {
      "type": "email",
      "person": "Stephen Cuppett",
      "message_count": 1,
      "messages": [{"subject": "...", "body_snippet": "...", "from_me": false}]
    }
  ]
}
```

If the JSON file doesn't exist or has no conversations, write a minimal section and exit.

---

## Step 3: Summarize Each Conversation

For each conversation, generate a **single concise line** (~15 words max) capturing the topic(s) discussed. Use semicolons to separate distinct sub-topics within one conversation.

**Tone:** Topic-focused, not message-count-focused. Useful for future reference ("who do I ask about X?").

**Rules:**
- Distinguish work topics from personal/social chat with natural language (don't use a tag, just be clear)
- For DMs: capture the primary topic(s), not pleasantries
- For threads: note the channel and who else was involved
- For email: use the subject line and body snippet as clues
- For MPDMs: treat like a group DM and list all participants

**Examples of good summaries:**
- `James Laska` → "OME authentication approach; second-system effect concerns vs KCP"
- `Adam Miller` → "Home networking (UniFi vs OpenWrt); Claude Code adoption in HCM"
- `#team-ocp-hypershift` → "workload identity for operator service accounts (with Adam Miller)"
- `Stephen Cuppett (email)` → "RHOBS production rollout sa-east-1 status"

---

## Step 4: Check for People Pages

For each person in a DM or MPDM conversation, check if a People page exists:
```
Glob: People/<person name>.md
```

- If the file exists: use `[[<person name>]]`
- If not: use just the plain name (no wiki-link)

For threads: don't wiki-link participants listed in the parenthetical — just use plain names.

---

## Step 5: Format the Section

```markdown
### Conversations

> [!info] Auto-updated on YYYY-MM-DD HH:MM

CORRECT callout format: `> [!info]` (single bracket). INCORRECT: `> [[!info]` (wiki-link syntax, never use).

- **[[James Laska]]** — OME authentication approach; second-system effect concerns vs KCP
- **[[Adam Miller]]** — Home networking (UniFi vs OpenWrt); Claude Code adoption in HCM
- **[[Christopher Alfonso]]** — JIRA CLI automation; agentic SDLC outcome tracking
- **[[Chris Sams]]** — Catching up; camping trip plans
- *#team-ocp-hypershift* — workload identity for operator service accounts (with Adam Miller, Bryan Cox)
- **[[Stephen Cuppett]]** *(email)* — RHOBS production rollout sa-east-1 status
```

**Format rules:**
- DMs and MPDMs first, sorted by message count descending (most active first)
- Public channel threads after DMs
- Email conversations last
- Combine Slack DM + email exchanges with the same person into one line if the topic overlaps; list separately if different topics
- If no conversations today, write: `*No conversations today.*`

---

## Step 6: Insert into Daily Note

Daily notes use section markers: `%% section:conversations %%` and `%% /section:conversations %%`.

**Use the `ReplaceSection` tool** to update the conversations section:
```
ReplaceSection(file_path="<daily note path>", section="conversations", content="### Conversations\n\n> [!info] Auto-updated on ...\n\n- ...")
```

The `content` parameter should include the `### Conversations` heading, the info callout, and all bullet points. The tool handles finding and replacing between the markers automatically.

**If the daily note does not have section markers**, fall back to the Edit tool: find `### Conversations` and replace up to the next `###` heading.

**Never touch other sections** — the ReplaceSection tool only modifies the content between the specified markers.

---

## Edge Cases

- **JSON file not found:** Write a minimal `### Conversations\n\n*No conversation data available.*` section
- **Empty conversations array:** Write `*No conversations today.*`
- **Daily note not found:** Print a warning and exit — do not create the note
- **Person appears in both Slack DM and email:** Combine into one bullet if topics overlap, separate bullets if distinct topics
