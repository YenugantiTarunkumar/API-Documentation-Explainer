# DocQuery 🔍

**Ask multi-step questions across OpenAPI specifications with an agentic, source-grounded RAG pipeline.**

---

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C?style=flat-square)
![BM25](https://img.shields.io/badge/Retrieval-BM25-FF6B35?style=flat-square)
![React](https://img.shields.io/badge/React-19+-61DAFB?style=flat-square&logo=react&logoColor=black)
![Langfuse](https://img.shields.io/badge/Langfuse-Observability-000000?style=flat-square)
![Groq](https://img.shields.io/badge/Groq-GPT--OSS-F55036?style=flat-square)
![Gemini](https://img.shields.io/badge/Gemini-Flash-4285F4?style=flat-square&logo=google&logoColor=white)
![HuggingFace](https://img.shields.io/badge/HuggingFace-Llama_3.1-FFD21E?style=flat-square&logo=huggingface&logoColor=black)

---

https://github.com/user-attachments/assets/84bf04d7-2583-4fc6-b5a4-e2d8bdf2a7c2

## Why This Project Matters

The standard advice for understanding an API is "just paste the spec into ChatGPT." That breaks down fast.

| Problem | DocQuery's Solution |
|---|---|
| Stripe's spec is ~50,000 lines - won't fit in any context window | RAG retrieves only the relevant chunks per query |
| Whole specifications are too large or sensitive to send on every request | Specs are indexed locally; the selected LLM receives bounded evidence and question/planning context, including recent history or specification names when needed |
| LLM training data has a cutoff - new endpoints are unknown | Re-ingest any time, answers always reflect the current spec |
| Raw LLM answers can't cite where they got the answer | Every response includes the exact source endpoints |
| Can't query multiple APIs simultaneously | Multi-spec support with separate BM25 indexes |
| Compound tasks collapse onto one likely endpoint | The agent decomposes workflows and balances evidence across every planned operation |
| A plausible answer can still be incomplete | Step-aware confidence scores each workflow step against its own evidence and permits one bounded retry |

---

## Features

- **RAG pipeline** - OpenAPI specs and documents are indexed with lightweight BM25 keyword retrieval. This avoids loading transformer models, but can be less effective when a query uses very different wording from the source.
- **`$ref` resolution** - request body schemas are dereferenced at ingest time, including `allOf`, `anyOf`, and `oneOf` composition patterns (up to 6 levels deep), making field names searchable with BM25.
- **Confidence scoring** - a lightweight estimate combines term-frequency cosine similarity with JSON field grounding. It does not use a semantic model or an LLM judge.
- **Source citations** - every answer includes the exact HTTP method + path that grounded it; endpoints cited in the final answer appear first in workflow order, followed by supporting retrieval evidence.
- **Multi-spec support** - ingest multiple APIs simultaneously and switch between them with one click
- **Dual ingest modes** - paste a public URL or upload a local `.json`, `.pdf`, or `.txt` file.
- **Persistent BM25 indexes** - indexes are stored under `backend/bm25_indexes` and retain their original specification names. They persist only when the hosting filesystem is persistent; Render free services may lose local files after restarts or redeploys.
- **Voice input** - record a question via the browser's MediaRecorder API; audio is transcribed by Whisper via Groq (~1s) and populated into the query box automatically.
- **Pipeline observability** - every query is traced end-to-end with Langfuse; retrieval span logs which endpoints were retrieved, the LLM generation span logs the full prompt and answer, and confidence scores are tracked as metrics across all queries.
- **LangGraph orchestration** - the full query lifecycle runs as a compiled `StateGraph`, with typed request state and confidence-driven conditional edges for bounded regeneration or rewrite-and-retrieval.
- **Confidence-gated self-correction** - when an answer scores below the grounding threshold, the agent makes one bounded retry and keeps the better-grounded attempt. Workflow retries preserve the balanced evidence set; single-operation retries may rewrite and retrieve again.
- **Workflow-aware answers** - compound questions are decomposed into at most three focused operations; evidence is labelled per operation, exact action matches are prioritized, and the answer must cover every step in order. Missing steps reduce confidence and trigger correction.
- **Workflow-aware confidence** - each answer step is scored only against the evidence retrieved for its corresponding operation; missing steps or missing labelled evidence contribute zero instead of letting unrelated chunks inflate the score.
- **Conversational follow-ups** - the browser sends the last three successful exchanges to resolve references such as "that endpoint" into standalone retrieval questions; the backend keeps no persistent conversation memory, and browser history resets when switching specifications. Provider calls and configured tracing can contain this context.
- **Cross-spec queries** - an "All specifications" mode routes questions to at most three relevant indexes, combines their evidence, and labels every cited endpoint with its source specification.

---

## Architecture

![Architecture](images/architecture.png)

The query path is a compiled LangGraph `StateGraph` rather than a single retrieve-and-generate call:

1. Resolve conversational references using up to three client-supplied history turns.
2. Route `All specifications` questions to at most three relevant local indexes.
3. Decompose compound questions into at most three ordered operations.
4. Retrieve and balance BM25 keyword evidence per operation, then compact it to the selected provider's budget.
5. Generate with Groq, Gemini, or Hugging Face and score each answer step only against its labelled evidence group.
6. Let the confidence node choose a conditional edge: finalize when the threshold is met, regenerate a workflow from the same balanced evidence, or rewrite a single-operation query and retrieve again. Stop after one corrective attempt and retain the higher-scoring result.
7. Return citations reordered to match the endpoints as they appear in the answer, followed by supporting evidence.

Planning uses the selected external LLM: contextualization sends the question and recent history when valid history is present; routing sends the question and available specification names for `All specifications` when more than three indexes exist; decomposition sends the resolved question to produce one to three retrieval queries. These are separate calls. With no history, one selected specification, and no retry, the normal path makes two LLM calls: decomposition and answer generation. The response's `agent.resolved_question` and `agent.selected_specs` come from the completed graph state.

The backend keeps indexes locally and does not persist conversation history as application memory. Query evidence and planning context are sent to the selected provider; optional voice input sends recorded audio to Groq Whisper. When Langfuse tracing is enabled, prompts (including retrieved evidence), answers, and run metadata are also sent to the configured Langfuse service.

---

## Design Decisions

**Summary-first chunking** - Each chunk starts with `{summary} - {METHOD} {path}` before the technical details. Synonym expansion is also injected into each chunk to improve keyword matching for natural-language queries.

**`$ref` resolution at ingest time** - OpenAPI specs use `$ref` pointers for all request/response schemas. Without resolving them, chunks contain `#/components/schemas/User` instead of the actual field names (`name`, `password`). The resolver handles `allOf`, `anyOf`, and `oneOf` composition up to 6 levels deep, so nested schemas are fully searchable.

**BM25 keyword retrieval** - Each query is tokenized and scored against the selected specification's chunks. Endpoint paths, operation names, parameter names, and injected synonyms improve exact keyword matching without loading embedding or reranking models.

**Bounded agent orchestration** - A LangGraph `StateGraph` resolves follow-ups, routes across specifications, and creates a plan of at most three operations before retrieval. Its confidence node conditionally finalizes, regenerates from balanced workflow evidence, or rewrites and returns to retrieval for a single-operation query. The graph is deliberately bounded to one corrective attempt, keeping latency and free-tier usage predictable.

**Provider-aware evidence budgets** - Groq, Gemini, and Hugging Face share the same orchestration path but receive different chunk and character budgets. Oversized schemas are compacted while preserving endpoint identity, required fields, and workflow-linking parameters. This prevents provider payload errors without weakening the plan itself.

**Lightweight confidence scoring** - Answer text is compared with retrieved evidence using term-frequency cosine similarity, and JSON examples are checked against known request fields. Workflow answers are scored against their labelled evidence groups; missing steps or evidence score zero. This is a lexical estimate, not a semantic hallucination detector.

**Per-spec BM25 indexes** - Each ingested specification gets its own `.pkl` index under `backend/bm25_indexes`. The saved index retains the original title, and filename hashes prevent different titles with similar normalized names from overwriting one another. Older application-created indexes can be listed when their original names remain in chunk metadata; otherwise, re-ingest the source document.

**Document ingestion** - URL and JSON OpenAPI ingestion use `extract_chunks()`; PDF and TXT uploads are split into searchable text chunks. Input checks reject invalid JSON and documents with no extractable text. Chunking and indexing run locally; query-time evidence and planning context are sent to whichever external LLM provider you select.

**Selectable LLM providers** - Groq GPT-OSS, Gemini Flash, and Hugging Face Llama use one provider-neutral prompt and expose their model, latency, call count, token usage, and evidence budget in each response. This makes answer quality and free-tier trade-offs directly comparable.

**Low-memory retrieval** - BM25 uses token matching and requires no transformer model. It is intentionally simpler than dense semantic retrieval, so differently worded queries may need more explicit keywords.

---

## Quick Start

### Prerequisites

- Python 3.11+
- React.js 18+
- At least one answer-provider credential: a [Groq API key](https://console.groq.com), [Gemini API key](https://aistudio.google.com/app/apikey), or [Hugging Face token](https://huggingface.co/settings/tokens)
- A Groq API key is also required if you want voice transcription

### Backend

Clone the repository:

```bash
git clone https://github.com/superb-striker/DocQuery
cd DocQuery
```

Create a virtual environment and install required libraries:

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```env
HF_TOKEN=your_token_here
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
```

Start the backend server:

```bash
uvicorn main:app --app-dir backend --reload
# API running at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

Install required packages and start the frontend server:

### Frontend

```bash
cd frontend
npm install
npm run dev
# UI running at http://localhost:5173
```

---

## API Reference

### `POST /ingest`

Fetch and index an OpenAPI spec from a public URL.

**Request**

```json
{
  "specification_url": "https://petstore3.swagger.io/api/v3/openapi.json"
}
```

**Response**

```json
{
  "specification_name": "Swagger Petstore - OpenAPI 3.0",
  "chunks_stored": 19,
  "message": "Successfully ingested 19 endpoints."
}
```

---

### `POST /ingest/file`

Upload a local `.json` spec file (for private/internal APIs).

**Request**

```
file: <your-openapi-spec.json>
```

**Response** - same as `/ingest`

---

### `POST /query`

Ask a question against one ingested spec, or use `"__all__"` to let the agent route across all available specifications. `history` is optional and is used only to resolve conversational references; it is not stored by the backend.

**Request**

```json
{
  "question": "How do I create a customer, attach a payment method, and create a subscription?",
  "specification_name": "stripe_api",
  "llm_provider": "groq",
  "history": [
    {
      "question": "How do I create a payment method?",
      "answer": "Use POST /v1/payment_methods ..."
    }
  ]
}
```

**Response**

```json
{
  "answer": "**Step 1: Create a customer** ...",
  "confidence": 71,
  "sources": [
    {
      "endpoint": "POST /v1/customers",
      "summary": "Create a customer",
      "specification": "stripe_api"
    }
  ],
  "llm": {
    "provider": "groq",
    "label": "Groq",
    "model": "openai/gpt-oss-120b",
    "max_chunks": 8,
    "max_evidence_chars": 10000,
    "calls": 2,
    "total_tokens": 2957
  },
  "latency_ms": 17032,
  "agent": {
    "attempts": 1,
    "retried": false,
    "selected_attempt": 1,
    "subqueries": [
      "Create a customer",
      "Attach a payment method to the customer",
      "Create a subscription for the customer"
    ],
    "resolved_question": "How do I create a customer, attach a payment method, and create a subscription?",
    "selected_specs": ["stripe_api"]
  }
}
```

---

### `GET /llm/providers`

List the configured answer providers and their current evidence budgets. `available` reports whether the corresponding environment variable is present.

**Response**

```json
{
  "providers": [
    {
      "id": "groq",
      "label": "Groq",
      "model": "openai/gpt-oss-120b",
      "max_chunks": 8,
      "max_evidence_chars": 10000,
      "available": true
    }
  ]
}
```

---

### `POST /transcribe`

Transcribe a browser audio recording to text via Groq Whisper, for use as a query.

**Request**

```json
file: <recording.webm>
```

**Response**

```json
{
  "transcript": "How do I authenticate with the API?"
}
```

---

### `GET /specifications`

List all currently ingested specification names.

**Response**

```json
{
  "specifications": ["Swagger Petstore - OpenAPI 3.0", "phantom_share"]
}
```

---

## Local Development

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `HF_TOKEN` | Optional | Hugging Face inference token; only needed when that provider is selected |
| `GROQ_API_KEY` | Recommended | Groq API key for GPT-OSS answers and Whisper voice transcription |
| `GEMINI_API_KEY` | Recommended | Google AI Studio key for Gemini answers |
| `LANGFUSE_PUBLIC_KEY` | Yes | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | Yes | Langfuse project secret key |
| `LANGFUSE_HOST` | Yes | Langfuse host (e.g. `https://jp.cloud.langfuse.com`) |

### Comparing LLM providers

Choose Groq, Gemini, or Hugging Face above the question box. Each response shows
the provider, model, latency, LLM call count, token usage (when reported), and
evidence budget. Groq receives at most 8 retrieved chunks within a 10,000-character,
schema-aware evidence budget; oversized request schemas are compacted while
preserving required and workflow-linking fields. Gemini and Hugging Face retain
larger evidence budgets.

### Resetting the Vector Store

```bash
# Wipe all ingested specs and start fresh
rm -rf backend/bm25_indexes/                       # Linux/Mac
Remove-Item -Recurse -Force backend\bm25_indexes # Windows PowerShell
```

---

## Limitations

- **Provider free tiers** - Groq, Gemini, and Hugging Face each enforce their own quotas and rate limits; the UI reports provider errors and lets you switch models.
- **Schema depth** - `$ref` resolution is capped at 6 levels. Deeply nested `$ref` chains beyond that are not resolved.
- **YAML specs** - only JSON OpenAPI specs are supported. For YAML specs, convert first: `python -c "import yaml,json,sys; json.dump(yaml.safe_load(open('spec.yaml')), open('spec.json','w'))"`.
- **Keyword retrieval** - BM25 can miss relevant passages when a question uses terminology that does not appear in the indexed text.
- **Ephemeral hosting storage** - Render free web services do not provide durable local storage; re-ingest documents after a restart or redeploy unless persistent storage is configured.

---
