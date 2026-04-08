---
name: obsidian-vault-query
description: |
  Search, query, and analyze Obsidian vault contents using the CLI's search index,
  graph awareness, and structured data features. Use when the user wants to:
  - Search the vault by content, tags, or properties
  - Find notes by frontmatter property values
  - Query backlinks or forward links for a note
  - Find orphan notes (no incoming links) or dead-end notes (no outgoing links)
  - Explore tags across the vault
  - Query tasks across all notes (todo/done)
  - Run Base queries and export results
  - Find unresolved links (wiki-links pointing to nonexistent files)
  - Analyze vault structure (word counts, outlines)
  - Prefer over grep/ripgrep for property-aware and link-aware queries
---

# Obsidian Vault Query Skill

The Obsidian CLI's query commands use the vault's internal search index and link graph — providing capabilities that grep/ripgrep cannot match: property-aware search, alias resolution, backlink traversal, and tag aggregation.

**Requires**: Obsidian running with CLI registered. See `obsidian-cli` skill for setup.

---

## Why CLI Search Over Grep

| Capability | CLI | grep/ripgrep |
|-----------|-----|-------------|
| Search by frontmatter property | Yes | Partial |
| Understand `[[wiki-links]]` | Yes | No |
| Resolve aliases | Yes | No |
| Find orphan notes | Yes | No |
| Aggregate tags across vault | Yes | No |
| Query tasks with context | Yes | No |
| Search with Obsidian's full-text index | Yes | No |
| Regex file content search | Partial | Yes |
| Edit file content | No | No |

Use **grep for raw text patterns** in known files; use **CLI for semantic/structural queries**.

---

## Search

```bash
# Basic full-text search (returns matching file paths)
obsidian search query="kubernetes"

# Search with context (shows matching lines like grep -C)
obsidian search:context query="managed services"

# Limit results
obsidian search query="ACS" limit=10

# Filter by path prefix
obsidian search query="backlog" path="Meetings/"

# Search by tag
obsidian search query="tag:#project"

# Search by property value
obsidian search query='attendees:[[Alice Smith]]'

# Open search results in Obsidian
obsidian search:open query="deployment strategy"
```

### Search syntax (Obsidian query language)

- `"exact phrase"` — phrase match
- `tag:#tagname` — by tag
- `file:filename` — by filename
- `path:folder/` — restrict to path
- `property:value` — by frontmatter property
- `-term` — exclude term
- `OR` — alternatives

---

## Link Graph

```bash
# Find all notes that link to a given note
obsidian backlinks file="People/Alice Smith.md"

# Find all links (outgoing) from a note
obsidian links file="Meetings/2026/03-March/02-Monday/2026-03-02-Team Sync.md"

# Find unresolved wiki-links (links pointing to nonexistent files)
obsidian unresolved

# Find orphan notes (no incoming backlinks)
obsidian orphans

# Find dead-end notes (no outgoing links)
obsidian deadends

# Get total count instead of full list
obsidian orphans total=true
obsidian backlinks file="Note.md" total=true

# JSON output for programmatic use
obsidian backlinks file="Note.md" format=json
```

---

## Tags

```bash
# List all tags in the vault
obsidian tags

# List tags with counts (most common first)
obsidian tags counts sort=count

# Get info about a specific tag
obsidian tag name="project"

# Get tag info with list of files using it
obsidian tag name="project" verbose=true
```

---

## Properties

```bash
# List all properties used across the vault
obsidian properties

# List properties grouped by file
obsidian properties by=file

# Read a specific property from a file
obsidian property:read file="Notes/My Note.md" name="status"

# Set a property value
obsidian property:set file="Notes/My Note.md" name="status" value="done"

# Remove a property
obsidian property:remove file="Notes/My Note.md" name="draft"

# List all aliases defined across the vault
obsidian aliases
```

---

## Tasks

```bash
# List all incomplete tasks across the entire vault
obsidian tasks todo

# List all completed tasks
obsidian tasks done

# List tasks from a specific file
obsidian tasks file="Projects/Your Project.md"

# List tasks from today's daily note
obsidian tasks daily

# Show tasks with file path and line number
obsidian tasks todo verbose=true

# Toggle a task's completion status (by file + line ref)
obsidian task file="Notes/My Note.md" ref=42 toggle=true

# Set task status explicitly
obsidian task file="Notes/My Note.md" ref=42 status=done
```

---

## Bases

```bash
# List all Base files in the vault
obsidian bases

# List views defined in a Base
obsidian base:views file="jira/Bases/Active Issues.md"

# Query a Base and return results
obsidian base:query file="jira/Bases/Active Issues.md"

# Query with specific output format
obsidian base:query file="jira/Bases/Active Issues.md" format=json
obsidian base:query file="jira/Bases/Active Issues.md" format=csv
obsidian base:query file="jira/Bases/Active Issues.md" format=tsv
obsidian base:query file="jira/Bases/Active Issues.md" format=md

# Return only file paths from a Base query
obsidian base:query file="jira/Bases/Active Issues.md" format=paths
```

---

## Outline & Word Count

```bash
# Get the heading outline of a note
obsidian outline file="Projects/Your Project.md"

# Get word count for a note
obsidian wordcount file="Projects/Your Project.md"

# Word count for all files in a folder
obsidian wordcount folder="Meetings/2026"
```

---

## Vault-Specific Recipes

### Find all meetings with a specific person

```bash
obsidian search query='attendees:[[Alice Smith]]' path="Meetings/"
```

### Find orphan notes that should be linked

```bash
obsidian orphans
```

### List all incomplete tasks across the vault

```bash
obsidian tasks todo verbose=true
```

### See today's daily note tasks

```bash
obsidian tasks daily
```

### Query a Base for export

```bash
obsidian base:query file="jira/Bases/Active Issues.md" format=json
```

### Find unresolved links (wiki-links without target files)

```bash
obsidian unresolved
```

### Tags by popularity

```bash
obsidian tags counts sort=count
```

### Find all files linking to a person page

```bash
obsidian backlinks file="People/Alice Smith.md" format=json
```

### Find dead-end notes (no outgoing links — potential ZK stubs)

```bash
obsidian deadends
```

### Search with context (like grep -C 2)

```bash
obsidian search:context query="your project topic" path="Meetings/"
```

### Audit property usage across vault

```bash
obsidian properties
```

---

## Combining CLI Search with Direct Access

The recommended pattern:

1. **Discover** with CLI: `obsidian search query="X"` → get file list
2. **Read** with Read tool: `Read file="path/from/search"` → get content
3. **Edit** with Edit tool: precise section-level changes

Example: "Find all meetings where we discussed FIPS and summarize the key points"
```bash
# Step 1: CLI search
obsidian search:context query="FIPS" path="Meetings/"
# Step 2: Read the relevant files with Read tool
# Step 3: Summarize from content
```
