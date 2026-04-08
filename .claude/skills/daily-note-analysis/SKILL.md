# Daily Note Analysis

Utilities for analyzing daily note quality and identifying cleanup candidates.

## Scripts

**analyze_daily_notes.py**: Counts daily notes with 30%+ empty sections.
```bash
python3 .claude/skills/daily-note-analysis/analyze_daily_notes.py
```

**detailed_analysis.py**: Section-by-section breakdown with statistics.
```bash
python3 .claude/skills/daily-note-analysis/detailed_analysis.py
```

Both scripts resolve the vault root via `Path(__file__).resolve().parents[3]`.
