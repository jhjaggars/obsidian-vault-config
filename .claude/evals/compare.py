#!/usr/bin/env python3
"""Aggregate promptfoo eval results into a comparison report.

Usage:
    python3 compare.py [results_dir]

Reads all *-2026-*.json files in results/ and produces a markdown comparison table.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def load_results(results_dir: Path) -> dict:
    """Load all result JSON files, grouped by eval name."""
    evals = {}
    for f in sorted(results_dir.glob("*-v3.json")):
        eval_name = f.stem.rsplit("-v3", 1)[0]
        with open(f) as fh:
            evals[eval_name] = json.load(fh)
    return evals


def extract_scores(data: dict) -> dict[str, dict]:
    """Extract per-provider pass rates from a promptfoo result file."""
    results = data.get("results", {}).get("results", [])
    provider_stats = defaultdict(lambda: {"pass": 0, "fail": 0, "error": 0, "total": 0})

    for r in results:
        label = r.get("provider", {}).get("label", "unknown")
        provider_stats[label]["total"] += 1
        if r.get("error"):
            provider_stats[label]["error"] += 1
        elif r.get("success"):
            provider_stats[label]["pass"] += 1
        else:
            provider_stats[label]["fail"] += 1

    return dict(provider_stats)


def main():
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "results"
    evals = load_results(results_dir)

    if not evals:
        print("No result files found in", results_dir)
        sys.exit(1)

    all_providers = set()
    eval_scores = {}
    for eval_name, data in evals.items():
        scores = extract_scores(data)
        eval_scores[eval_name] = scores
        all_providers.update(scores.keys())

    providers = sorted(all_providers)

    print("# Gemma 4 Eval Comparison Report")
    print()
    print(f"Generated from {len(evals)} eval suite(s), {len(providers)} providers")
    print()

    # Summary table
    print("## Pass Rates by Provider")
    print()
    header = "| Eval | " + " | ".join(providers) + " |"
    sep = "|------|" + "|".join(["------"] * len(providers)) + "|"
    print(header)
    print(sep)

    provider_totals = defaultdict(lambda: {"pass": 0, "total": 0})

    for eval_name in sorted(eval_scores.keys()):
        scores = eval_scores[eval_name]
        row = f"| {eval_name} |"
        for p in providers:
            s = scores.get(p, {"pass": 0, "total": 0})
            total = s["total"]
            passed = s["pass"]
            pct = f"{100 * passed / total:.0f}%" if total > 0 else "N/A"
            row += f" {passed}/{total} ({pct}) |"
            provider_totals[p]["pass"] += passed
            provider_totals[p]["total"] += total
        print(row)

    # Totals row
    row = "| **TOTAL** |"
    for p in providers:
        t = provider_totals[p]
        pct = f"{100 * t['pass'] / t['total']:.0f}%" if t["total"] > 0 else "N/A"
        row += f" **{t['pass']}/{t['total']} ({pct})** |"
    print(row)

    print()
    print("## Failure Details")
    print()

    for eval_name in sorted(eval_scores.keys()):
        data = evals[eval_name]
        results = data.get("results", {}).get("results", [])
        failures = [r for r in results if not r.get("success") and not r.get("error")]
        if not failures:
            continue

        print(f"### {eval_name}")
        print()
        for r in failures:
            provider = r.get("provider", {}).get("label", "unknown")
            msg = r.get("vars", {}).get("user_message", "").split("\n")[0][:60]
            reasons = []
            gr = r.get("gradingResult")
            if gr:
                for c in gr.get("componentResults", []):
                    if c and not c.get("pass"):
                        reasons.append((c.get("reason") or "")[:150])
            reason_str = reasons[0] if reasons else "unknown"
            print(f"- **{provider}**: {msg}")
            print(f"  - {reason_str}")
        print()


if __name__ == "__main__":
    main()
