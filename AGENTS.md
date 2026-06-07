# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Active Portfolio

Jesse Jaggars — distinguished engineer in Red Hat's Hybrid Platforms org, focused on AI SDLC and Hosted OpenShift (HyperShift/ROSA) platform strategy and engineering productivity.

**Areas of Responsibility:**
- [[Areas/Engineering Productivity|Engineering Productivity]] — developer tooling, CI/CD, internal platform onboarding
- [[Areas/HyperShift and ROSA Platform|HyperShift & ROSA Platform]] — architecture, feature evaluation, cross-team coordination
- [[Areas/AI and Agentic Strategy|AI & Agentic Strategy]] — AI SDLC readiness, agentic tooling adoption
- [[Areas/Team Leadership|Team Leadership]] — hiring, 1:1s, team health

**Current Focus (Mature):** ROSA Boundary, HCMSTRAT-15 Agentic Coding Readiness, Agentic SDLC Pilot
**In Development (Early):** Fleetshift, Sharded ETCD, Nested Virtualization, BGP ROSA HCP, Ambient Code Platform, RFE Enrichment Pipeline, Scale From Zero Azure Annotator

## Repository Overview

This is an Obsidian vault for personal knowledge management, including meeting notes, daily notes, documentation, and a Zettelkasten (ZK) system. The vault uses several Obsidian plugins including Templater, Dataview, and Excalidraw.

## Vault Structure

- **Areas/**: Ongoing responsibilities with no end date. Each area note describes scope, active projects, and key channels/people.
- **Projects/**: Project notes (template: `Templates/Project.md`). Frontmatter: `status`, `area`, `jira_keys`, `keywords`, `pipeline`. Sections use `%% section:name %%` markers for safe agent editing. Standard sections: Status, Goal, Team, Timeline, Notes, Related Items (auto-generated).
  - `Projects/Work/Archived/` — completed or inactive projects. Agents should skip this folder.
- **Meetings/**: Meeting notes organized by `YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md` format
- **daily/**: Daily notes in `YYYY/MM-Month/YYYY-MM-DD-Day.md`
- **People/**: Person pages with dossiers (~650 pages)
- **Reference/**: Reference material — read specific files on demand
- **docs/**: Documentation, strategies, ADRs (~195 files, see `docs/INDEX.md` for categories)
- **SOP/**: Standard Operating Procedures
- **Personal/**: Personal notes including travel, family, health, hobbies, and side projects
- **jira/**, **prs/**, **Drive/**: Synced external data (Base notes with frontmatter for Dataview queries)
- **YouTube/**: Video transcripts and analysis
- **`.claude/vault-reference.md`**: Detailed docs for Templater config, Python utilities, `@claude` directives — load on demand, not in every session

## Learned Patterns

Check `.claude/memory/` for learned patterns and preferences that should be applied when working in this vault.

## Git Workflow

This is a git repository tracking the vault contents. The `.gitignore` excludes `.obsidian/*` metadata.
