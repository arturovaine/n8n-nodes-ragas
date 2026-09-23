#!/usr/bin/env python3
"""Ragas evaluation runner for the n8n-nodes-ragas community node.

Reads a JSON payload ``{config, samples}`` from stdin, runs the selected Ragas
metrics with the configured judge LLM + embeddings, and writes a JSON result
``{results, summary, sample_count}`` to stdout. Everything else (progress,
warnings, errors) goes to stderr so stdout only ever carries the result JSON.
"""
import contextlib
import json
import sys

# Metrics that cannot be scored without a ground-truth reference.
REFERENCE_REQUIRED = {"context_recall", "answer_correctness", "semantic_similarity"}


def eprint(*args):
    print(*args, file=sys.stderr)


def fail(message, code=1):
    eprint(message)
    sys.exit(code)


def normalize_contexts(value, delimiter=""):
    """Coerce a contexts field into a list of strings.

    Accepts a list (used as-is), or a string (split on ``delimiter`` when one is
    provided, otherwise treated as a single context). ``None`` becomes ``[]``.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value)
    if delimiter:
        return [part.strip() for part in text.split(delimiter) if part.strip()]
    return [text]


def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def find_missing_references(samples, metrics):
    """Return indices of samples lacking a reference when one is required."""
    if not REFERENCE_REQUIRED.intersection(metrics):
        return []
    return [i for i, sample in enumerate(samples) if _is_blank(sample.get("reference"))]


def build_rows(samples, delimiter=""):
    """Map incoming samples to Ragas EvaluationDataset rows."""
    rows = []
    for sample in samples:
        row = {
            "user_input": "" if sample.get("question") is None else str(sample.get("question")),
            "response": "" if sample.get("answer") is None else str(sample.get("answer")),
            "retrieved_contexts": normalize_contexts(sample.get("contexts"), delimiter),
        }
        reference = sample.get("reference")
        if not _is_blank(reference):
            row["reference"] = str(reference)
        rows.append(row)
    return rows


def build_llm(cfg):
    provider = (cfg.get("provider") or "openai").lower()
    model = cfg.get("model") or ""
    api_key = cfg.get("api_key") or ""
    base_url = cfg.get("base_url") or ""

    if provider in ("openai", "ollama", "local"):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            fail(f"Missing package 'langchain-openai'. Install it with: pip install langchain-openai. ({exc})")
        kwargs = {"model": model or "gpt-4o-mini", "api_key": api_key or "not-needed"}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            fail(f"Missing package 'langchain-anthropic'. Install it with: pip install langchain-anthropic. ({exc})")
        kwargs = {"model": model or "claude-3-5-sonnet-latest"}
        if api_key:
            kwargs["api_key"] = api_key
        return ChatAnthropic(**kwargs)

    if provider in ("google", "gemini"):
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            fail(f"Missing package 'langchain-google-genai'. Install it with: pip install langchain-google-genai. ({exc})")
        kwargs = {"model": model or "gemini-1.5-flash"}
        if api_key:
            kwargs["google_api_key"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)

    fail(f"Unsupported judge provider: {provider}")


def build_embeddings(cfg):
    provider = (cfg.get("provider") or "openai").lower()
    model = cfg.get("model") or ""
    api_key = cfg.get("api_key") or ""
    base_url = cfg.get("base_url") or ""

    if provider in ("openai", "ollama", "local"):
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            fail(f"Missing package 'langchain-openai'. Install it with: pip install langchain-openai. ({exc})")
        kwargs = {"model": model or "text-embedding-3-small", "api_key": api_key or "not-needed"}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAIEmbeddings(**kwargs)

    if provider in ("google", "gemini"):
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as exc:
            fail(f"Missing package 'langchain-google-genai'. Install it with: pip install langchain-google-genai. ({exc})")
        kwargs = {"model": model or "models/embedding-001"}
        if api_key:
            kwargs["google_api_key"] = api_key
        return GoogleGenerativeAIEmbeddings(**kwargs)

    if provider in ("huggingface", "hf", "sentence-transformers"):
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:
            fail(f"Missing package 'langchain-huggingface'. Install it with: pip install langchain-huggingface sentence-transformers. ({exc})")
        return HuggingFaceEmbeddings(model_name=model or "sentence-transformers/all-MiniLM-L6-v2")

    fail(f"Unsupported embeddings provider: {provider}")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON payload on stdin: {exc}")

    config = payload.get("config") or {}
    samples = payload.get("samples") or []
    metrics = config.get("metrics") or []

    if not metrics:
        fail("No metrics selected.")
    if not samples:
        fail("No samples provided.")

    missing = find_missing_references(samples, metrics)
    if missing:
        needed = sorted(REFERENCE_REQUIRED.intersection(metrics))
        fail(
            f"Metrics {needed} require a reference for every sample, but samples "
            f"at indices {missing} have none. Map a Reference Field or remove those metrics."
        )

    delimiter = (config.get("options") or {}).get("contexts_delimiter") or ""
    rows = build_rows(samples, delimiter)

    # Keep stdout clean: send any library chatter to stderr, restore afterwards.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            from ragas import EvaluationDataset, evaluate
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
            from ragas.metrics import (
                answer_correctness,
                answer_relevancy,
                answer_similarity,
                context_precision,
                context_recall,
                faithfulness,
            )
        except ImportError as exc:
            fail(
                "The 'ragas' package is not installed in this Python environment. "
                "Install the requirements (see requirements.txt): "
                "pip install ragas langchain-openai. "
                f"Original error: {exc}"
            )

        metric_map = {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_precision": context_precision,
            "context_recall": context_recall,
            "answer_correctness": answer_correctness,
            "semantic_similarity": answer_similarity,
        }

        selected = []
        name_by_key = {}
        for key in metrics:
            metric = metric_map.get(key)
            if metric is None:
                fail(f"Unknown metric: {key}")
            selected.append(metric)
            name_by_key[key] = getattr(metric, "name", key)

        llm = LangchainLLMWrapper(build_llm(config.get("llm") or {}))
        embeddings = LangchainEmbeddingsWrapper(build_embeddings(config.get("embeddings") or {}))

        dataset = EvaluationDataset.from_list(rows)
        result = evaluate(dataset=dataset, metrics=selected, llm=llm, embeddings=embeddings)
        frame = result.to_pandas()

        import pandas as pd

        results = []
        for i in range(len(frame)):
            scores = {}
            for key in metrics:
                column = name_by_key[key]
                value = frame[column].iloc[i] if column in frame.columns else None
                scores[key] = None if value is None or pd.isna(value) else float(value)
            results.append({"index": i, "scores": scores})

        summary = {}
        for key in metrics:
            column = name_by_key[key]
            if column in frame.columns:
                series = frame[column].dropna()
                summary[key] = float(series.mean()) if len(series) else None
            else:
                summary[key] = None

        out = {"results": results, "summary": summary, "sample_count": len(frame)}

    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
