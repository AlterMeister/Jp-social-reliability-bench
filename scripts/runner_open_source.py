import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

DEFAULT_SYSTEM_PROMPT = (
    "あなたは誠実で優秀な日本語アシスタントです。"
    "指示がない限り、日本語で自然かつ簡潔に回答してください。"
    "与えられた場面・文脈に沿って返答してください。"
)

GENERATION_CONFIG = {
    "max_new_tokens": 256,
    "do_sample": True,
    "temperature": 0.6,
    "top_p": 0.9,
}

def parse_args():
    parser = argparse.ArgumentParser(
        description="Run benchmark JSON/JSONL file(s) against a specified model."
    )
    parser.add_argument(
        "--model_name",
        type=str,
        required=True,
        help='Hugging Face model name or local model path, e.g. "Qwen/Qwen3-32B"',
    )
    parser.add_argument(
        "--benchmark_path",
        type=str,
        required=True,
        help=(
            "Path to a benchmark .json/.jsonl file or a directory containing multiple files."
        ),
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
        "--max_new_tokens",
        type=int,
        default=GENERATION_CONFIG["max_new_tokens"],
        help="Maximum number of new tokens to generate.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=GENERATION_CONFIG["temperature"],
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--top_p",
        type=float,
        default=GENERATION_CONFIG["top_p"],
        help="Top-p sampling value.",
    )
    parser.add_argument(
        "--do_sample",
        action="store_true",
        help="Enable sampling. If not set, greedy decoding is used.",
    )
    parser.add_argument(
        "--system_prompt",
        type=str,
        default=DEFAULT_SYSTEM_PROMPT,
        help="Optional system prompt override.",
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

def build_messages_from_item(
    item: Dict[str, Any],
    system_prompt: str,
) -> List[Dict[str, str]]:
    prompt = get_prompt_text(item)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def is_qwen3_model(model_name: str) -> bool:
    return "Qwen3" in model_name

def load_model_and_tokenizer(model_name: str):
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    return model, tokenizer

def apply_model_chat_template(
    tokenizer,
    messages: List[Dict[str, str]],
    model_name: str,
) -> str:
    if is_qwen3_model(model_name):
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

def generate_text(
    model,
    tokenizer,
    model_name: str,
    messages: List[Dict[str, str]],
    max_new_tokens: int = 512,
    do_sample: bool = True,
    temperature: float = 0.6,
    top_p: float = 0.9,
) -> str:
    text = apply_model_chat_template(
        tokenizer=tokenizer,
        messages=messages,
        model_name=model_name,
    )
    model_inputs = tokenizer(
        [text],
        return_tensors="pt",
        add_special_tokens=False,
    ).to(model.device)
    generation_kwargs: Dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
    }

    if do_sample:
        generation_kwargs["temperature"] = temperature
        generation_kwargs["top_p"] = top_p
    with torch.no_grad():
        generated_ids = model.generate(
            **model_inputs,
            **generation_kwargs,
        )

    output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
    output_text = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
    return output_text

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
    model_name: str,
    system_prompt: str,
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


def run_single_item(
    item: Dict[str, Any],
    model,
    tokenizer,
    model_name: str,
    system_prompt: str,
    generation_config: Dict[str, Any],
    benchmark_file: Optional[str] = None,
    context_variant: Optional[str] = None,
) -> Dict[str, Any]:
    messages = build_messages_from_item(
        item=item,
        system_prompt=system_prompt,
    )

    response = generate_text(
        model=model,
        tokenizer=tokenizer,
        model_name=model_name,
        messages=messages,
        max_new_tokens=generation_config.get("max_new_tokens", 512),
        do_sample=generation_config.get("do_sample", True),
        temperature=generation_config.get("temperature", 0.6),
        top_p=generation_config.get("top_p", 0.9),
    )

    return make_result_record(
        item=item,
        response_text=response,
        system_prompt=system_prompt,
        model_name=model_name,
        generation_config=generation_config,
        benchmark_file=benchmark_file,
        context_variant=context_variant,
    )

def run_benchmark(
    items: List[Dict[str, Any]],
    model,
    tokenizer,
    model_name: str,
    system_prompt: str,
    generation_config: Dict[str, Any],
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
                model=model,
                tokenizer=tokenizer,
                model_name=model_name,
                system_prompt=system_prompt,
                generation_config=generation_config,
                benchmark_file=benchmark_file,
                context_variant=context_variant,
            )
        except Exception as e:
            result = make_error_record(
                item=item,
                error=e,
                model_name=model_name,
                system_prompt=system_prompt,
                generation_config=generation_config,
                benchmark_file=benchmark_file,
                context_variant=context_variant,
            )
        results.append(result)
    return results

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
            raise ValueError(
                f"Benchmark file must be .json or .jsonl: {benchmark_path}"
            )
        return [path]

    files = sorted(
        p for p in path.glob("*")
        if p.is_file() and p.suffix.lower() in valid_suffixes
    )
    if not files:
        raise FileNotFoundError(
            f"No JSON/JSONL benchmark files found under: {benchmark_path}"
        )
    return files

def build_output_path_for_file(
    model_name: str,
    benchmark_file: Path,
    output_dir: str = "results",
) -> Path:
    model_slug = slugify(Path(model_name).name or model_name)
    category_dir = benchmark_file.parent.name if benchmark_file.parent.name else "root"
    output_name = f"{benchmark_file.stem}.jsonl"
    return Path(output_dir) / model_slug / category_dir / output_name


if __name__ == "__main__":
    args = parse_args()

    model_name = args.model_name
    benchmark_path = args.benchmark_path
    benchmark_files = collect_benchmark_files(benchmark_path)

    generation_config = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": args.do_sample,
        "temperature": args.temperature,
        "top_p": args.top_p,
    }

    print(f"Benchmark source: {benchmark_path}")
    print(f"Discovered {len(benchmark_files)} benchmark file(s).")
    for file_path in benchmark_files:
        print(f" - {file_path}")

    print(f"\nLoading model: {model_name}")
    model, tokenizer = load_model_and_tokenizer(model_name)

    for benchmark_file in benchmark_files:
        output_path = build_output_path_for_file(
            model_name=model_name,
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
            model=model,
            tokenizer=tokenizer,
            model_name=model_name,
            system_prompt=args.system_prompt,
            generation_config=generation_config,
            limit=args.limit,
            benchmark_file=benchmark_file.name,
            context_variant=context_variant,
        )

        save_jsonl(results, str(output_path))
        print(f"Saved results to: {output_path}")

"""
Example usage:

python -m scripts.runner_open_source \
  --model_name "/data/model/Qwen3-32B" \
  --benchmark_path "configs/jp_benchmark_v0.jsonl" \
  --output_dir ".out" \
  --do_sample

python -m scripts.runner_open_source \
  --model_name "/data/model/Llama-3-ELYZA-JP-8B" \
  --benchmark_path "configs/jp_benchmark_v0.jsonl" \
  --output_dir ".out" \
  --do_sample

python -m scripts.runner_open_source \
  --model_name "/data/model/llm-jp-4-8b-thinking" \
  --benchmark_path "configs/jp_benchmark_v0.jsonl" \
  --output_dir ".out" \
  --do_sample
"""