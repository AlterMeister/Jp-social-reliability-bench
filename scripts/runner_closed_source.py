from src.llms_closed.api_qwen import Qwen
from src.llms_closed.api_gpt import GPT
from src.llms_closed.api_deepseek import DeepSeek
from src.llms_closed.api_claude import Claude
from src.llms_closed.api_grok import Grok
from src.llms_closed.api_gemini import Gemini

import argparse
import json
import re
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_SYSTEM_PROMPT = (
    "あなたは誠実で優秀な日本語アシスタントです。"
    "指示がない限り、日本語で自然かつ簡潔に回答してください。"
    "与えられた場面・文脈に沿って返答してください。"
)

GENERATION_CONFIG = {
    "temperature": 0.6,
    "max_new_tokens": 256,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run benchmark JSON/JSONL file(s) against a closed-source API model."
    )
    parser.add_argument(
        "--provider",
        type=str,
        required=True,
        choices=["claude", "gemini", "qwen", "gpt", "deepseek"],
        help="API model provider",
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--benchmark_path",
        type=str,
        required=True,
        help="Path to a benchmark .json/.jsonl file or a directory containing multiple files.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="results",
        help='Root directory to save result JSONL files. Default: "results"',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of benchmark items to run per file.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=GENERATION_CONFIG["temperature"],
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--max_new_tokens",
        type=int,
        default=GENERATION_CONFIG["max_new_tokens"],
        help="Maximum number of new tokens to generate.",
    )
    parser.add_argument(
        "--system_prompt",
        type=str,
        default=DEFAULT_SYSTEM_PROMPT,
        help="Optional system prompt override.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Whether to log token usage if the provider returns it.",
    )
    return parser.parse_args()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("/", "_")
    text = text.replace("\\", "_")
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = re.sub(r"(^[_\-.]+|[_\-.]+$)", "", text)
    return text


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {e}") from e
            if not isinstance(obj, dict):
                raise ValueError(
                    f"Each JSONL line must be a JSON object. Got {type(obj)} at {path}:{line_no}"
                )
            items.append(obj)
    return items


def save_jsonl(data: List[Dict[str, Any]], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_benchmark_items(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".jsonl":
        return load_jsonl(path)

    if suffix == ".json":
        data = load_json(path)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        raise ValueError("Benchmark JSON must be either a list or {'items': [...]}.")

    raise ValueError(f"Unsupported benchmark format: {path}")


def get_prompt_text(item: Dict[str, Any]) -> str:
    prompt = (item.get("prompt_text") or item.get("prompt") or "").strip()
    if not prompt:
        raise ValueError(
            "Missing 'prompt_text' (or fallback 'prompt') field in item: "
            f"{item.get('item_id') or item.get('prompt_id') or '[unknown]'}"
        )
    return prompt


def make_result_record(
    item: Dict[str, Any],
    response_text: str,
    system_prompt: str,
    model_name: str,
    generation_config: Dict[str, Any],
    benchmark_file: Optional[str] = None,
    context_variant: Optional[str] = None,
) -> Dict[str, Any]:
    prompt_text = get_prompt_text(item)

    result = dict(item)
    result.update(
        {
            "prompt_text": prompt_text,
            "model_name": model_name,
            "system_prompt": system_prompt,
            "generation_config": generation_config,
            "benchmark_file": benchmark_file,
            "context_variant": context_variant,
            "response": response_text,
        }
    )
    return result


def make_error_record(
    item: Dict[str, Any],
    error: Exception,
    system_prompt: str,
    model_name: str,
    generation_config: Dict[str, Any],
    benchmark_file: Optional[str] = None,
    context_variant: Optional[str] = None,
) -> Dict[str, Any]:
    result = dict(item)
    result.update(
        {
            "model_name": model_name,
            "system_prompt": system_prompt,
            "generation_config": generation_config,
            "benchmark_file": benchmark_file,
            "context_variant": context_variant,
            "error": str(error),
        }
    )
    return result


def get_context_variant_from_file(path: Path) -> str:
    stem = path.stem
    if stem == "meta":
        return "baseline"
    if stem.startswith("meta_"):
        return stem[len("meta_"):]
    return stem


def collect_benchmark_files(benchmark_path: str) -> List[Path]:
    path = Path(benchmark_path)
    if not path.exists():
        raise FileNotFoundError(f"Benchmark path not found: {benchmark_path}")

    valid_suffixes = {".json", ".jsonl"}

    if path.is_file():
        if path.suffix.lower() not in valid_suffixes:
            raise ValueError(f"Benchmark file must be .json or .jsonl: {benchmark_path}")
        return [path]

    files = sorted(
        p for p in path.glob("*")
        if p.is_file() and p.suffix.lower() in valid_suffixes
    )
    if not files:
        raise FileNotFoundError(f"No JSON/JSONL benchmark files found under: {benchmark_path}")
    return files


def build_output_path_for_file(
    provider: str,
    model_name: str,
    benchmark_file: Path,
    output_dir: str = "results",
) -> Path:
    provider_slug = slugify(provider)
    model_slug = slugify(Path(model_name).name or model_name)
    category_dir = benchmark_file.parent.name if benchmark_file.parent.name else "root"
    output_name = f"{benchmark_file.stem}.jsonl"
    return Path(output_dir) / provider_slug / model_slug / category_dir / output_name


def build_llm(
    provider: str,
    model_name: Optional[str],
    temperature: float,
    max_new_tokens: int,
    report: bool = False,
):
    if provider == "claude":
        return Claude(
            model_name=model_name,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            report=report,
        )
    if provider == "gemini":
        return Gemini(
            model_name=model_name,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            report=report,
        )
    if provider == "qwen":
        return Qwen(
            model_name=model_name,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            report=report,
        )
    if provider == "gpt":
        return GPT(
            model_name=model_name,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            report=report,
        )
    if provider == "deepseek":
        return DeepSeek(
            model_name=model_name,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            report=report,
        )
    raise ValueError(f"Unsupported provider: {provider}")


def run_single_item(
    item: Dict[str, Any],
    llm,
    system_prompt: str,
    generation_config: Dict[str, Any],
    model_name: str,
    benchmark_file: Optional[str] = None,
    context_variant: Optional[str] = None,
) -> Dict[str, Any]:
    prompt_text = get_prompt_text(item)

    # 优先尝试带 system_prompt 的接口
    try:
        response_text = llm.request(prompt_text, system_prompt=system_prompt)
    except TypeError:
        # 兼容你当前还没改签名的 request(query)
        merged_prompt = f"{system_prompt}\n\n{prompt_text}" if system_prompt else prompt_text
        response_text = llm.request(merged_prompt)

    return make_result_record(
        item=item,
        response_text=response_text,
        system_prompt=system_prompt,
        model_name=model_name,
        generation_config=generation_config,
        benchmark_file=benchmark_file,
        context_variant=context_variant,
    )


def run_benchmark(
    items: List[Dict[str, Any]],
    llm,
    system_prompt: str,
    generation_config: Dict[str, Any],
    model_name: str,
    limit: Optional[int] = None,
    benchmark_file: Optional[str] = None,
    context_variant: Optional[str] = None,
) -> List[Dict[str, Any]]:
    target_items = items[:limit] if limit is not None else items
    results: List[Dict[str, Any]] = []

    for idx, item in enumerate(target_items, start=1):
        item_name = (
            item.get("item_id")
            or item.get("prompt_id")
            or item.get("condition")
            or f"item_{idx}"
        )
        print(f"[{idx}/{len(target_items)}] Running {item_name} ...")

        try:
            result = run_single_item(
                item=item,
                llm=llm,
                system_prompt=system_prompt,
                generation_config=generation_config,
                model_name=model_name,
                benchmark_file=benchmark_file,
                context_variant=context_variant,
            )
        except Exception as e:
            result = make_error_record(
                item=item,
                error=e,
                system_prompt=system_prompt,
                model_name=model_name,
                generation_config=generation_config,
                benchmark_file=benchmark_file,
                context_variant=context_variant,
            )

        results.append(result)

    return results


if __name__ == "__main__":
    args = parse_args()

    benchmark_files = collect_benchmark_files(args.benchmark_path)

    llm = build_llm(
        provider=args.provider,
        model_name=args.model_name,
        temperature=args.temperature,
        max_new_tokens=args.max_new_tokens,
        report=args.report,
    )

    resolved_model_name = getattr(llm, "model_name", args.model_name or args.provider)

    generation_config = {
        "temperature": args.temperature,
        "max_new_tokens": args.max_new_tokens,
    }

    print(f"Benchmark source: {args.benchmark_path}")
    print(f"Discovered {len(benchmark_files)} benchmark file(s).")
    for file_path in benchmark_files:
        print(f" - {file_path}")

    print(f"\nUsing provider: {args.provider}")
    print(f"Resolved model name: {resolved_model_name}")

    for benchmark_file in benchmark_files:
        output_path = build_output_path_for_file(
            provider=args.provider,
            model_name=resolved_model_name,
            benchmark_file=benchmark_file,
            output_dir=args.output_dir,
        )
        context_variant = get_context_variant_from_file(benchmark_file)

        print(f"\nLoading benchmark file: {benchmark_file}")
        print(f"Context variant: {context_variant}")
        print(f"Resolved output path: {output_path}")

        items = load_benchmark_items(str(benchmark_file))
        print(f"Loaded {len(items)} item(s).")

        results = run_benchmark(
            items=items,
            llm=llm,
            system_prompt=args.system_prompt,
            generation_config=generation_config,
            model_name=resolved_model_name,
            limit=args.limit,
            benchmark_file=benchmark_file.name,
            context_variant=context_variant,
        )

        save_jsonl(results, str(output_path))
        print(f"Saved results to: {output_path}")

'''
python -m scripts.runner_closed_source \
  --provider claude \
  --model_name claude-haiku-4-5-20251001 \
  --benchmark_path configs/jp_benchmark_v0.jsonl \
  --output_dir .out \
  --temperature 0.01 \
  --max_new_tokens 128 \
  --report

python -m scripts.runner_closed_source \
  --provider gemini \
  --model_name gemini-3-flash-preview \
  --benchmark_path configs/jp_benchmark_v0.jsonl \
  --output_dir .out \
  --temperature 0.01 \
  --max_new_tokens 128 \
  --report

python -m scripts.runner_closed_source \
  --provider qwen \
  --model_name qwq-32b \
  --benchmark_path configs/jp_benchmark_v0.jsonl \
  --output_dir .out \
  --temperature 0.01 \
  --max_new_tokens 128 \
  --report

python -m scripts.runner_closed_source \
  --provider gpt \
  --model_name gpt-5.1 \
  --benchmark_path configs/jp_benchmark_v0.jsonl \
  --output_dir .out \
  --temperature 0.01 \
  --max_new_tokens 128 \
  --report

python -m scripts.runner_closed_source \
  --provider deepseek \
  --model_name deepseek-chat \
  --benchmark_path configs/jp_benchmark_v0.jsonl \
  --output_dir .out \
  --temperature 0.01 \
  --max_new_tokens 128 \
  --report
'''
