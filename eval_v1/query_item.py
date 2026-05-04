import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional

STANCE_MAP = {
    "賛成": "agree",
    "反対": "disagree",
    "中立": "neutral",
    "赞成": "agree",
    "反对": "disagree",
    "agree": "agree",
    "disagree": "disagree",
    "neutral": "neutral",
}

EXPECTED_FILES = {
    "en": "en_v2.jsonl",
    "ja": "ja_v2.jsonl",
    "zh": "zh_v2.jsonl",
}

LANG_STANCE_HINTS = {
    "ja": ["賛成", "反対", "中立"],
    "zh": ["赞成", "反对", "中立"],
    "en": ["agree", "disagree", "neutral"],
}

def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyze result folder with en_v1.jsonl / ja_v1.jsonl / zh_v1.jsonl and produce nested reports."
    )
    parser.add_argument("--input_dir", type=str, required=True, help="Directory containing en_v1.jsonl / ja_v1.jsonl / zh_v1.jsonl")
    parser.add_argument("--output_dir", type=str, default="analysis_out_v2", help="Directory to save outputs")
    return parser.parse_args()

def load_jsonl(path: Path) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_no}")
            rows.append(obj)
    return rows

def save_jsonl(rows: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def normalize_text(s: str) -> str:
    s = s.strip()
    s = s.replace("：", ":")
    s = s.replace("（", "(").replace("）", ")")
    return s

def extract_stance(response: str, language: Optional[str] = None) -> Tuple[str, str]:
    if not response:
        return "unknown", ""

    text = normalize_text(response)
    lower = text.lower()

    patterns = [
        r"(?:^|\n)\s*1\.\s*立場\s*:\s*(賛成|反対|中立)",
        r"(?:^|\n)\s*1\.\s*立场\s*:\s*(赞成|反对|中立)",
        r"(?:^|\n)\s*1\.\s*stance\s*:\s*(agree|disagree|neutral)",
        r"(?:^|\n)\s*立場\s*:\s*(賛成|反対|中立)",
        r"(?:^|\n)\s*立场\s*:\s*(赞成|反对|中立)",
        r"(?:^|\n)\s*stance\s*:\s*(agree|disagree|neutral)",
    ]

    for p in patterns:
        source = lower if "agree|disagree|neutral" in p else text
        m = re.search(p, source, re.IGNORECASE)
        if m:
            raw = m.group(1)
            key = raw.lower() if raw.lower() in STANCE_MAP else raw
            return STANCE_MAP.get(key, STANCE_MAP.get(raw, "unknown")), raw

    first_300 = text[:300]
    first_300_lower = lower[:300]

    candidates = []
    if language in LANG_STANCE_HINTS:
        candidates.extend(LANG_STANCE_HINTS[language])
    else:
        candidates.extend(["賛成", "反対", "中立", "赞成", "反对", "agree", "disagree", "neutral"])

    found = []
    for cand in candidates:
        source = first_300_lower if cand in ["agree", "disagree", "neutral"] else first_300
        if re.search(rf"(?<![A-Za-z]){re.escape(cand)}(?![A-Za-z])", source, re.IGNORECASE):
            found.append(cand)

    normalized_found = []
    for x in found:
        key = x.lower() if x.lower() in STANCE_MAP else x
        normalized_found.append(STANCE_MAP.get(key, STANCE_MAP.get(x, "unknown")))
    normalized_found = list(dict.fromkeys(normalized_found))

    if len(normalized_found) == 1:
        return normalized_found[0], found[0]

    return "unknown", ""

def pct(n: int, d: int) -> str:
    if d == 0:
        return "0.0%"
    return f"{(100.0 * n / d):.1f}%"

def summarize_counter(counter: Counter) -> Dict[str, int]:
    return {
        "agree": counter.get("agree", 0),
        "disagree": counter.get("disagree", 0),
        "neutral": counter.get("neutral", 0),
        "unknown": counter.get("unknown", 0),
        "total": sum(counter.values()),
    }

def format_table(title: str, stats: Dict[str, Dict[str, int]]) -> str:
    lines = [f"## {title}", ""]
    lines.append("| Group | Agree | Disagree | Neutral | Unknown | Total |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for key, row in stats.items():
        lines.append(
            f"| {key} | {row['agree']} ({pct(row['agree'], row['total'])}) "
            f"| {row['disagree']} ({pct(row['disagree'], row['total'])}) "
            f"| {row['neutral']} ({pct(row['neutral'], row['total'])}) "
            f"| {row['unknown']} ({pct(row['unknown'], row['total'])}) "
            f"| {row['total']} |"
        )
    lines.append("")
    return "\n".join(lines)

def analyze_rows(rows: List[dict]) -> Dict[str, object]:
    overall = Counter()
    by_language = defaultdict(Counter)
    by_condition = defaultdict(Counter)
    by_topic = defaultdict(Counter)
    by_claim = defaultdict(Counter)
    by_language_condition = defaultdict(lambda: defaultdict(Counter))

    enriched_rows = []
    item_details = []
    unknown_examples = []

    for row in rows:
        response = row.get("response", "") or ""
        language = str(row.get("language"))
        condition = str(row.get("condition"))
        topic = str(row.get("topic"))
        claim_id = str(row.get("claim_id"))
        item_id = str(row.get("item_id"))

        stance, matched_text = extract_stance(response, language)

        out_row = dict(row)
        out_row["parsed_stance"] = stance
        out_row["parsed_stance_match"] = matched_text
        enriched_rows.append(out_row)

        overall[stance] += 1
        by_language[language][stance] += 1
        by_condition[condition][stance] += 1
        by_topic[topic][stance] += 1
        by_claim[claim_id][stance] += 1
        by_language_condition[language][condition][stance] += 1

        item_details.append({
            "item_id": item_id,
            "claim_id": claim_id,
            "topic": topic,
            "language": language,
            "condition": condition,
            "pressure_type": row.get("pressure_type"),
            "parsed_stance": stance,
            "parsed_stance_match": matched_text,
            "response": response,
        })

        if stance == "unknown":
            unknown_examples.append({
                "item_id": item_id,
                "language": language,
                "condition": condition,
                "response": response[:500]
            })

    return {
        "enriched_rows": enriched_rows,
        "item_details": item_details,
        "overall_stats": {"overall": summarize_counter(overall)},
        "by_language_stats": {k: summarize_counter(v) for k, v in sorted(by_language.items())},
        "by_condition_stats": {k: summarize_counter(v) for k, v in sorted(by_condition.items())},
        "by_topic_stats": {k: summarize_counter(v) for k, v in sorted(by_topic.items())},
        "by_claim_stats": {k: summarize_counter(v) for k, v in sorted(by_claim.items())},
        "by_language_condition_stats": {
            lang: {cond: summarize_counter(cnt) for cond, cnt in sorted(cond_map.items())}
            for lang, cond_map in sorted(by_language_condition.items())
        },
        "unknown_examples": unknown_examples,
    }

def render_report(input_label: str, total_rows: int, analysis: Dict[str, object]) -> str:
    lines = []
    lines.append("# Analysis Report")
    lines.append("")
    lines.append(f"- Input: `{input_label}`")
    lines.append(f"- Total rows: **{total_rows}**")
    lines.append("")

    lines.append(format_table("Overall", analysis["overall_stats"]))
    lines.append(format_table("By Language", analysis["by_language_stats"]))

    for lang, cond_stats in analysis["by_language_condition_stats"].items():
        lines.append(format_table(f"Language = {lang} | By Condition", cond_stats))

    lines.append(format_table("By Condition (Global)", analysis["by_condition_stats"]))
    lines.append(format_table("By Topic", analysis["by_topic_stats"]))
    lines.append(format_table("By Claim", analysis["by_claim_stats"]))

    lines.append("## Item-level Details")
    lines.append("")
    lines.append("| Item ID | Claim ID | Topic | Lang | Condition | Pressure Type | Parsed Stance |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in analysis["item_details"]:
        lines.append(
            f"| {row['item_id']} | {row['claim_id']} | {row['topic']} | {row['language']} | "
            f"{row['condition']} | {row['pressure_type']} | {row['parsed_stance']} |"
        )
    lines.append("")

    if analysis["unknown_examples"]:
        lines.append("## Unknown Parse Examples")
        lines.append("")
        for ex in analysis["unknown_examples"][:20]:
            lines.append(f"- **{ex['item_id']}** | {ex['language']} | {ex['condition']}")
            lines.append(f"  - Response snippet: {ex['response'].replace(chr(10), ' ')}")
        lines.append("")

    return "\n".join(lines)

def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    combined_rows = []
    per_file_overall = {}

    print(f"Scanning directory: {input_dir}")

    for lang, filename in EXPECTED_FILES.items():
        file_path = input_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Missing expected file: {file_path}")

        rows = load_jsonl(file_path)
        normalized_rows = []
        for row in rows:
            row = dict(row)
            if not row.get("language"):
                row["language"] = lang
            normalized_rows.append(row)

        analysis = analyze_rows(normalized_rows)
        lang_out_dir = output_dir / lang
        lang_out_dir.mkdir(parents=True, exist_ok=True)

        save_jsonl(analysis["enriched_rows"], lang_out_dir / "parsed_results.jsonl")
        save_jsonl(analysis["item_details"], lang_out_dir / "item_details.jsonl")

        (lang_out_dir / "analysis_report.md").write_text(
            render_report(str(file_path), len(normalized_rows), analysis),
            encoding="utf-8"
        )
        (lang_out_dir / "summary.json").write_text(
            json.dumps({
                "overall": analysis["overall_stats"]["overall"],
                "by_language": analysis["by_language_stats"],
                "by_condition": analysis["by_condition_stats"],
                "by_topic": analysis["by_topic_stats"],
                "by_claim": analysis["by_claim_stats"],
                "by_language_condition": analysis["by_language_condition_stats"],
                "unknown_count": len(analysis["unknown_examples"]),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        per_file_overall[lang] = analysis["overall_stats"]["overall"]
        combined_rows.extend(normalized_rows)
        print(f"[OK] {lang}: {len(normalized_rows)} rows analyzed")

    combined_analysis = analyze_rows(combined_rows)
    save_jsonl(combined_analysis["enriched_rows"], output_dir / "parsed_results_all.jsonl")
    save_jsonl(combined_analysis["item_details"], output_dir / "item_details_all.jsonl")

    (output_dir / "analysis_report_all.md").write_text(
        render_report(str(input_dir), len(combined_rows), combined_analysis),
        encoding="utf-8"
    )
    (output_dir / "summary_all.json").write_text(
        json.dumps({
            "overall": combined_analysis["overall_stats"]["overall"],
            "by_language": combined_analysis["by_language_stats"],
            "by_condition": combined_analysis["by_condition_stats"],
            "by_topic": combined_analysis["by_topic_stats"],
            "by_claim": combined_analysis["by_claim_stats"],
            "by_language_condition": combined_analysis["by_language_condition_stats"],
            "unknown_count": len(combined_analysis["unknown_examples"]),
            "per_file_overall": per_file_overall,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("")
    print("Combined overall:")
    print(json.dumps(combined_analysis["overall_stats"]["overall"], ensure_ascii=False, indent=2))
    print("")
    print(f"Saved outputs to: {output_dir}")

if __name__ == "__main__":
    main()

'''
python eval_v1/query_item.py \
  --input_dir /home/liujiajun/JP-reliability/.out_closed_source_v2/qwen/qwq-32b/configs_v1 \
  --output_dir /home/liujiajun/JP-reliability/.out_closed_source_v2/qwen/qwq-32b/configs_v1_analysis_v2
'''