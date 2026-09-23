# Design: n8n-nodes-ragas

**Date:** 2026-09-23
**Author:** Arturo Vaine
**Status:** Approved (v1 scope)

## Summary

A community n8n node package that brings [Ragas](https://docs.ragas.io/) RAG
evaluation into n8n workflows. A single node — **Ragas Evaluate** — scores a
dataset of RAG samples against a selected set of metrics using an LLM-as-judge
plus an embeddings model.

Like the sibling `n8n-nodes-sklearn` package, this is **self-hosted n8n only**:
it executes Python via `child_process` and requires Python with `ragas` and the
relevant LangChain provider packages installed. It cannot pass n8n Cloud's
community-node verification.

## Motivation

Ragas is the de-facto standard for evaluating RAG pipelines, but it is
Python-only and LLM-driven. Teams building RAG flows in n8n currently have no
native way to measure faithfulness, answer relevancy, or context quality inside
their automation. This node closes that gap: pipe your RAG outputs in, get
metric scores out, branch on thresholds downstream.

## Key design decision: LLM wiring

Almost every Ragas metric is **LLM-as-judge** — it needs an LLM and (usually) an
embeddings model. This is the defining difference from the sklearn package,
which is pure compute.

**Decision:** The node instantiates the LLM/embeddings **inside the spawned
Python process**, driven by node parameters (provider + model) and an n8n
**credential** for the API key. Ragas natively wraps LangChain models in Python,
so this is the path of least resistance and matches how the library is meant to
be used.

**Rejected alternatives:**
- *n8n AI sub-node connection* (`ai_languageModel` / `ai_embedding` input ports):
  prettiest n8n UX, but an architectural trap — the chat model lives in n8n's JS
  runtime while Ragas runs in a separate Python process, with no clean bridge for
  Python to call back into the sub-node. Deferred as a possible v2.
- *Env-vars only*: too opaque, cannot mix providers per node.

## Architecture

Single node `RagasEvaluate` (`INodeType`). Flow:

1. TS node collects parameters + input items.
2. Builds a JSON payload `{ config, samples }`.
3. Spawns `python3 ragas_runner.py` and writes the payload to the process's
   **stdin** (not argv — eval datasets carry large context blobs that can exceed
   OS argv length limits).
4. `ragas_runner.py` constructs the Ragas dataset, configures the judge LLM +
   embeddings from `config`, runs `ragas.evaluate(...)`, and writes results as
   JSON to **stdout**.
5. TS node parses stdout and emits n8n items.

### Python bridge: shipped script + stdin/stdout

Chosen over sklearn's inline `-c` + argv pattern because:
- Ragas evaluation scripts are long and benefit from being real, lintable files.
- Datasets with retrieved contexts are large; stdin avoids argv size limits.
- The Python is independently testable with pytest.

`gulp` copies `ragas_runner.py` (and the `.svg` icon) into `dist` at build time.

A long-running Python sidecar (persistent process / local HTTP) was considered
for keeping the LLM client warm across calls, but rejected for v1 as too much
lifecycle complexity.

## Node interface (parameters)

- **Metrics** (multi-select, v1 set):
  - Faithfulness
  - Answer / Response Relevancy
  - Context Precision
  - Context Recall
  - Answer Correctness
  - Semantic Similarity
- **Field mapping** (which incoming item field holds each part of a sample):
  - Question Field
  - Answer Field
  - Contexts Field (accepts an array, or a delimited string)
  - Reference Field (ground truth; required only for some metrics — see table)
- **Judge LLM**:
  - Provider: OpenAI / Anthropic / Google Gemini / Ollama-compatible
  - Model name
  - Base URL (optional; for Ollama / OpenAI-compatible local endpoints)
- **Embeddings**:
  - Provider: OpenAI / Google / Ollama / HuggingFace-local
  - Model name
  - *Note:* Anthropic has no embeddings API. When judge = Anthropic, the user
    must choose an embeddings provider. `HuggingFace-local` (sentence-transformers)
    is the default that needs no API key.
- **Python Path** (default `python3`).
- **Advanced**: request timeout, batch size.

### Metric → required fields

| Metric              | Needs Reference | Needs Embeddings |
|---------------------|:---------------:|:----------------:|
| Faithfulness        |        no       |        no        |
| Answer Relevancy    |        no       |       yes        |
| Context Precision   |    no (LLM)*    |        no        |
| Context Recall      |       yes       |        no        |
| Answer Correctness  |       yes       |        no        |
| Semantic Similarity |       yes       |       yes        |

\* LLM-based context precision uses the question + response + contexts; a
reference-based variant may be added later.

## Credentials

One n8n credential type: **Ragas LLM API**
- `apiKey` (string, may be empty for Ollama / HuggingFace-local)
- `baseUrl` (string, optional)

Reused for both the judge and the embeddings provider. Keeping keys in a
credential (rather than a plaintext string param, as sklearn's `pythonPath`-style
params do) is a deliberate improvement.

## Output format

- **Per input item:** the original item passes through with metric scores
  appended (`faithfulness`, `answer_relevancy`, `context_precision`, …).
- **Final summary item:** mean score per metric across all samples, plus sample
  count and the list of metrics run. Makes downstream threshold/branch logic
  trivial.

## Error handling

- Capture and surface Python `stderr` verbatim on non-zero exit.
- Friendly, specific messages for the common failure modes:
  - `ragas` / LangChain provider package not installed
  - missing or invalid API key
  - a mapped field not present on an item
  - empty / missing contexts
- Honour `continueOnFail()` (emit `{ error }` item) as sklearn nodes do.

## Repository structure

```
n8n-nodes-ragas/
  nodes/RagasEvaluate/RagasEvaluate.node.ts
  nodes/RagasEvaluate/ragas_runner.py
  nodes/RagasEvaluate/ragas.svg
  credentials/RagasLlmApi.credentials.ts
  package.json
  tsconfig.json
  gulpfile.js
  .eslintrc.js
  .gitignore
  README.md
  requirements.txt        # ragas, langchain-openai, langchain-anthropic, ...
  test/                    # pytest for ragas_runner.py + sample payload
  docs/superpowers/specs/  # this spec
```

Toolchain mirrors `n8n-nodes-sklearn`: TypeScript, `gulp` (icon + `.py` copy),
`eslint` with `eslint-plugin-n8n-nodes-base`, `prettier`. `package.json` declares
the node and the credential under the `n8n` key.

## Testing

- **Python (`ragas_runner.py`):** pytest using a Ragas fake/echo LLM so tests run
  offline without API keys. Verify each metric path produces a score and that
  reference-requiring metrics fail cleanly when the reference is absent.
- **TypeScript:** a small harness that pipes a sample `{config, samples}` payload
  through the node's spawn logic and asserts the parsed output shape. `lint` and
  `build` must pass.

## Scope boundaries (YAGNI)

Explicitly **out** of v1:
- Synthetic test-set generation (Ragas `TestsetGenerator`) — candidate for a
  second node later.
- Non-LLM metrics (BLEU/ROUGE/string-match) and advanced metrics (Noise
  Sensitivity, Aspect Critic, Rubric scoring, Factual Correctness, Context
  Entities Recall).
- Per-metric convenience nodes — the single batch-evaluate node matches how Ragas
  works; per-metric nodes may be added later if there's demand.
- n8n AI sub-node (`ai_languageModel`) integration — possible v2.

## Install location

`/Users/arturovaine/Documents/Projects/AI-ML/n8n-nodes-ragas`
