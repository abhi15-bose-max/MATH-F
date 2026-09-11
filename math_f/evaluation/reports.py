"""Writes the end-of-run report trio (spec section 33): summary.json,
summary.csv, and a human-readable summary.md.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path


def _pct(x) -> str:
    return f"{x * 100:.1f}%" if x is not None else "n/a"


def render_markdown_table(metrics: dict) -> str:
    max_attempts = metrics["max_attempts"]
    cumulative = metrics["cumulative_success_by_attempt"]
    rows = [
        ("Tasks evaluated", str(metrics["total_tasks"])),
    ]
    for k in range(1, max_attempts + 1):
        label = f"{k}-shot cumulative success" if k > 1 else "1-shot success"
        rows.append((label, _pct(cumulative.get(f"cumulative_success_{k}_shot"))))
    failed_pct = metrics["abstained_tasks"] / metrics["total_tasks"] if metrics["total_tasks"] else None
    rows.append((f"Failed after {max_attempts}", _pct(failed_pct)))
    mean_attempts = metrics["mean_attempts_to_success"]
    rows.append(("Mean attempts to success", f"{mean_attempts:.2f}" if mean_attempts is not None else "n/a"))
    rows.append(("Malformed outputs", str(metrics["malformed_output_count"])))
    rows.append(("Infrastructure aborts", str(metrics["infrastructure_abort_count"])))

    lines = ["| Metric | Result |", "|---|---:|"]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def _render_full_markdown(metrics: dict) -> str:
    lines = ["# MATH-F Evaluation Summary", ""]
    lines.append(render_markdown_table(metrics))
    lines.append("")
    lines.append("## Exact attempt distribution")
    lines.append("")
    lines.append("(number of tasks whose *first successful* attempt was exactly attempt k)")
    lines.append("")
    lines.append("| Attempt | Count |")
    lines.append("|---|---:|")
    for k, v in sorted(
        metrics["exact_attempt_distribution"].items(),
        key=lambda kv: int(kv[0].rsplit("_", 1)[1]),
    ):
        attempt_num = k.rsplit("_", 1)[1]
        lines.append(f"| {attempt_num} | {v} |")
    lines.append("")
    lines.append("## Failure class counts (across all attempts)")
    lines.append("")
    if metrics["failure_class_counts"]:
        lines.append("| Failure class | Count |")
        lines.append("|---|---:|")
        for cls, count in sorted(metrics["failure_class_counts"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {cls} | {count} |")
    else:
        lines.append("_No failures recorded._")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Total attempts logged: {metrics['total_attempts_logged']}")
    lines.append(f"- Total generation tokens: {metrics['total_generation_tokens']}")
    lines.append(f"- Total input tokens: {metrics['total_input_tokens']}")
    lines.append(f"- Total generation time: {metrics['total_generation_time_seconds']}s")
    lines.append(f"- Total verification time: {metrics['total_verification_time_seconds']}s")
    lines.append("")
    return "\n".join(lines)


def write_reports(run_dir, metrics: dict) -> dict:
    summaries_dir = Path(run_dir) / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    json_path = summaries_dir / "summary.json"
    json_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    csv_path = summaries_dir / "summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in metrics.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    writer.writerow([f"{key}.{sub_key}", sub_value])
            else:
                writer.writerow([key, value])

    md_path = summaries_dir / "summary.md"
    md_path.write_text(_render_full_markdown(metrics), encoding="utf-8")

    return {"json": json_path, "csv": csv_path, "md": md_path}
