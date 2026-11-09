"""Rebuildable Markdown, standalone HTML and CSV reports from JSON evidence."""

import csv
import html
import json
import re
import statistics
from pathlib import Path

METRICS = ("engine_prefill_tps", "engine_decode_tps", "client_output_tps", "ttft_seconds",
           "first_visible_seconds", "wall_seconds", "max_chunk_gap_seconds", "prompt_tokens", "completion_tokens")


def summarize(data):
    rows = []
    coding = []
    for model in data["models"]:
        trials = model.get("speed", [])
        for unit, size in sorted({(t["input_unit"], t["input_size"]) for t in trials}):
            attempts = [t for t in trials if (t["input_unit"], t["input_size"]) == (unit, size)]
            ok = [t for t in attempts if t["status"] == "ok"]
            row = {"model": model["id"], "provider": model["provider"],
                   "release_date": model.get("release_date") or "unknown", "input_unit": unit, "input_size": size,
                   "successful_runs": len(ok), "attempted_runs": len(attempts)}
            for metric in METRICS:
                values = [t[metric] for t in ok if t.get(metric) is not None]
                row[metric] = statistics.median(values) if values else None
                row[metric + "_min"] = min(values) if values else None
                row[metric + "_max"] = max(values) if values else None
            rows.append(row)
        tasks = model.get("coding", [])
        if tasks or data.get("suite") in ("coding", "all"):
            completed = [t for t in tasks if t.get("status") == "completed"]
            expected = model.get("coding_tasks_expected", len(tasks))
            coding.append({"model": model["id"], "completed": len(completed), "expected": expected,
                           "passed": sum(bool(t.get("passed")) for t in completed),
                           "checks_passed": sum(t.get("checks_passed", 0) for t in completed),
                           "checks_total": sum(t.get("checks_total", 0) for t in completed),
                           "seconds": sum(t.get("seconds", 0) for t in tasks)})
    return rows, coding


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def number(value, decimals=2):
    return "N/A" if value is None else f"{value:,.{decimals}f}"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(map(cell, headers)) + " |",
                       "| " + " | ".join("---" for _ in headers) + " |",
                       *["| " + " | ".join(map(cell, row)) + " |" for row in rows]])


def build_report(data):
    rows, coding = summarize(data)
    parts = ["# LLM BenchKit report", f"Run: {data.get('run_id', 'unknown')} · Status: {data.get('status', 'unknown')}",
             "## Scope and environment", "```json\n" + json.dumps(data.get("environment", {}), indent=2, ensure_ascii=False) + "\n```",
             "Sequential, single-request text-model trials. Runtime configuration, model metadata and raw observations "
             "are retained in results.json. Release dates are supplied by the config, not discovered or verified automatically."]
    parts += ["## Models", table(["ID", "Provider", "Model/API identifier", "Release", "Release source"], [
        [m["id"], m["provider"], m.get("model", ""), m.get("release_date") or "unknown", m.get("release_source", "")]
        for m in data["models"]])]
    if rows:
        parts += ["## Speed (medians of successful trials)", table(
            ["Model", "Input target", "Runs OK/attempted", "Engine prefill tok/s", "Engine decode tok/s",
             "Client output tok/s", "First chunk s", "First visible text s"], [
                [r["model"], f"{r['input_size']} {r['input_unit']}", f"{r['successful_runs']}/{r['attempted_runs']}",
                 number(r["engine_prefill_tps"]), number(r["engine_decode_tps"]), number(r["client_output_tps"]),
                 number(r["ttft_seconds"]), number(r["first_visible_seconds"])] for r in rows])]
        parts += ["Engine rates are reported only when returned by the backend. Client output rate is reported completion "
                  "tokens divided by total request time, including network, queueing and prompt processing; it is not engine "
                  "decode speed. First chunk includes exposed reasoning; first visible text excludes it. Hidden reasoning "
                  "and provider buffering can change both observations. Missing usage means N/A, not zero.",
                  "llama.cpp raw trials use exact tokenizer-sized input, disable prompt reuse and request a fixed output "
                  "length with ignore_eos. Other providers receive equal character counts, use chat templates and may stop "
                  "early. Their prompt caches are not forcibly disabled. These modes are not equivalent workloads. Inspect "
                  "actual token counts, cached tokens, output lengths, min/max and errors in CSV/JSON before comparing. "
                  "Ollama's prompt_eval_count and duration describe its reported prompt evaluation, not necessarily total cached context."]
    if coding:
        parts += ["## Coding edits", table(["Model", "Tasks evaluated/expected", "Full tasks passed", "Checks passed/evaluated", "Time s"], [
            [r["model"], f"{r['completed']}/{r['expected']}", r["passed"],
             f"{r['checks_passed']}/{r['checks_total']}", number(r["seconds"])] for r in coding]),
            "The built-in suite has three small synthetic projects and 27 checks, not SWE-bench. Custom task suites "
            "can differ. Infrastructure/API errors are excluded from evaluated totals and shown below; they are not scored "
            "as model failures. Tests are visible to the agent. Container isolation and read-only test mounts do not make "
            "the suite resistant to deliberate benchmark gaming."]
        eligible = [r for r in coding if r["expected"] > 0 and r["completed"] == r["expected"]]
        if eligible:
            best = max(eligible, key=lambda r: (r["passed"] / r["expected"], r["checks_passed"] / max(r["checks_total"], 1)))
            ties = [r["model"] for r in eligible if (r["passed"] / r["expected"], r["checks_passed"] / max(r["checks_total"], 1)) ==
                    (best["passed"] / best["expected"], best["checks_passed"] / max(best["checks_total"], 1))]
            parts += ["Observed coding leaders among fully evaluated configurations: " + ", ".join(map(cell, ties)) +
                      ". This ranks this run's task/check pass fractions only; it is not a universal model or daily-use recommendation."]
    errors = []
    for m in data["models"]:
        errors += [f"{m['id']}: {e}" for e in m.get("errors", [])]
        errors += [f"{m['id']} speed {t['input_size']}: {t['error']}" for t in m.get("speed", []) if t["status"] == "error"]
        errors += [f"{m['id']} coding {t['id']}: {t.get('error') or t.get('errors') or 'infrastructure error'}"
                   for t in m.get("coding", []) if t["status"] == "error"]
    if errors:
        parts += ["## Errors and incomplete coverage", "\n".join("- " + cell(e) for e in errors)]
    parts += ["## Interpretation", "Short runs do not prove sustained stability, coding correctness outside these fixtures, "
              "or equivalence to a hosted assistant. Keep engine versions, quantization, hardware, context capacity, "
              "reasoning budgets and sampling settings comparable. This tool does not automatically choose those settings "
              "or measure GPU memory, power, model load time, concurrency, vision or audio.",
              "## Artifacts", "- results.json: raw trials, configuration, coding transcripts and edited files\n"
              "- speed.csv: per-input medians and ranges\n- coding.csv: evaluated tasks and checks\n"
              "- report.html: standalone escaped HTML report"]
    return "\n\n".join(parts) + "\n"


def write_reports(data, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    md = build_report(data)
    (directory / "report.md").write_text(md, encoding="utf-8")
    # No external resources or executable content; safe to open offline.
    sections = []
    for block in md.split("\n\n"):
        if block.startswith("```json\n"):
            sections.append("<pre>" + html.escape(block[8:].removesuffix("\n```")) + "</pre>")
        elif block.startswith("#"):
            level = len(block) - len(block.lstrip("#"))
            sections.append(f"<h{level}>" + html.escape(block[level:].strip()) + f"</h{level}>")
        elif block.startswith("| "):
            lines = block.splitlines()
            def cells(line):
                return [html.escape(v.strip().replace("\\|", "|")) for v in re.split(r"(?<!\\)\|", line)[1:-1]]
            headers = "".join("<th>" + v + "</th>" for v in cells(lines[0]))
            body = "".join("<tr>" + "".join("<td>" + v + "</td>" for v in cells(line)) + "</tr>" for line in lines[2:])
            sections.append("<div class='scroll'><table><thead><tr>" + headers + "</tr></thead><tbody>" + body + "</tbody></table></div>")
        elif block.startswith("- "):
            sections.append("<ul>" + "".join("<li>" + html.escape(line[2:]) + "</li>" for line in block.splitlines()) + "</ul>")
        else:
            sections.append("<p>" + html.escape(block) + "</p>")
    page = ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>LLM BenchKit report</title><style>body{max-width:1100px;margin:2rem auto;'
            'padding:0 1rem;font:15px/1.6 system-ui;color:#172033;background:#fafbfd}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;background:#edf1f7}'
            '.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}'
            'th,td{text-align:left;border:1px solid #d3dbe6;padding:.6rem}th{background:#e9eff8}'
            'h1,h2{color:#163a68}</style>' + "\n".join(sections) + '</html>')
    (directory / "report.html").write_text(page, encoding="utf-8")
    rows, coding = summarize(data)
    for filename, values, defaults in (("speed.csv", rows, ["model", "input_size"]),
                                        ("coding.csv", coding, ["model", "completed", "expected"])):
        with (directory / filename).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(values[0]) if values else defaults)
            writer.writeheader()
            # Neutralize spreadsheet formulas in untrusted model IDs/metadata.
            writer.writerows({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                              for k, v in row.items()} for row in values)
