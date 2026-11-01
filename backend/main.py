import json
import time
from typing import Literal

import httpx
from agent import (
    order_chunks_by_answer_citations,
    run_agent_graph,
)
from confidence import score_confidence
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from ingest import (
    extract_chunks,
    fetch_specification,
    extract_document_chunks,
)
from langfuse import get_client, observe
from llm import (
    LLMProviderError,
    build_contextualization_prompt,
    build_prompt,
    build_query_decomposition_prompt,
    build_retrieval_rewrite_prompt,
    build_specification_routing_prompt,
    get_llm_metrics,
    get_provider_api_key,
    get_provider_config,
    provider_catalog,
    query_llm,
    reset_llm_metrics,
)
from loggerConfig import get_logger
from pydantic import BaseModel, Field
from sources import format_chunk_reference, format_source
from vectorStore import list_specifications, retrieve_hybrid, store_chunks

load_dotenv()
langfuse = get_client()

logger = get_logger("main")
ALL_SPECIFICATIONS = "__all__"

app = FastAPI(title="DocQuery")



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    specification_url: str

class ConversationTurn(BaseModel):
    question: str
    answer: str

class QueryRequest(BaseModel):
    question: str
    specification_name: str
    history: list[ConversationTurn] = Field(default_factory=list)
    llm_provider: Literal["groq", "gemini", "huggingface"] = "groq"


# Observed helpers
@observe(name="hybrid-retrieval")
def run_retrieval(question: str, specification_name: str):
    chunks = retrieve_hybrid(
        query=question,
        specification_name=specification_name,
        num_results=20,
        rerank_top_n=5,
    )
    # Log what was retrieved so it's visible in the span
    langfuse.update_current_span(
        input={"question": question, "specification": specification_name},
        output={
            "chunks_returned": len(chunks) if chunks else 0,
            "sources": [
                format_chunk_reference(c.get("metadata", {}))
                for c in (chunks or [])
            ]
        }
    )
    return chunks


def specification_names() -> list[str]:
    return list_specifications()


def _extract_specification_chunks(specification: object) -> tuple[str, list[dict]]:
    if not isinstance(specification, dict) or not isinstance(
        specification.get("paths"), dict
    ):
        raise HTTPException(
            status_code=400,
            detail="The JSON must contain a valid API specification with paths.",
        )

    info = specification.get("info", {})
    if not isinstance(info, dict):
        raise HTTPException(
            status_code=400,
            detail="The API specification must contain valid info metadata.",
        )

    title = info.get("title")
    specification_name = (
        title.strip()
        if isinstance(title, str) and title.strip()
        else "Unknown API"
    )
    chunks = extract_chunks(specification)
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No usable API endpoints were found in the specification.",
        )
    return specification_name, chunks


def retrieve_from_specifications(question: str, selected_specs: list[str]):
    """Retrieve from each selected spec and interleave their ranked results."""
    results_by_spec = []
    for specification_name in selected_specs:
        tagged = []
        for chunk in run_retrieval(question, specification_name):
            tagged.append({
                **chunk,
                "metadata": {
                    **chunk.get("metadata", {}),
                    "collection_name": specification_name,
                },
            })
        results_by_spec.append(tagged)

    interleaved = []
    max_results = max((len(items) for items in results_by_spec), default=0)
    for index in range(max_results):
        for items in results_by_spec:
            if index < len(items):
                interleaved.append(items[index])
    return interleaved

@observe(name="llm-generate")
async def run_generation(prompt: str, provider: str):
    # Log the full prompt so you can debug what the LLM actually received
    langfuse.update_current_span(input={"prompt": prompt})
    answer = await query_llm(prompt, provider)
    langfuse.update_current_span(output={"answer": answer})
    return answer


@observe(name="rewrite-retrieval-query")
async def run_query_rewrite(
    question: str, answer: str, chunks: list[dict], provider: str
):
    prompt = build_retrieval_rewrite_prompt(question, answer, chunks)
    langfuse.update_current_span(input={"question": question})
    rewritten = (await query_llm(prompt, provider)).strip().strip('"\'')
    # Retrieval needs a compact query, not model commentary or multiple options.
    rewritten = " ".join(rewritten.splitlines()[:1])[:500]
    langfuse.update_current_span(output={"rewritten_query": rewritten})
    return rewritten


@observe(name="decompose-query")
async def run_query_decomposition(question: str, provider: str) -> list[str]:
    prompt = build_query_decomposition_prompt(question)
    langfuse.update_current_span(input={"question": question})
    raw_plan = (await query_llm(prompt, provider)).strip()
    try:
        start = raw_plan.index("[")
        end = raw_plan.rindex("]") + 1
        parsed = json.loads(raw_plan[start:end])
        plan = parsed if isinstance(parsed, list) else [question]
    except (ValueError, json.JSONDecodeError):
        plan = [question]
    langfuse.update_current_span(output={"subqueries": plan})
    return plan


@observe(name="contextualize-follow-up")
async def run_query_contextualization(
    question: str, history: list[dict], provider: str
) -> str:
    prompt = build_contextualization_prompt(question, history)
    langfuse.update_current_span(
        input={"question": question, "history_length": len(history)}
    )
    resolved = (await query_llm(prompt, provider)).strip()
    langfuse.update_current_span(output={"resolved_question": resolved})
    return resolved


@observe(name="route-specifications")
async def run_specification_routing(
    question: str,
    available_specs: list[str],
    provider: str,
) -> list[str]:
    prompt = build_specification_routing_prompt(question, available_specs)
    langfuse.update_current_span(
        input={"question": question, "available_specs": available_specs}
    )
    raw_selection = (await query_llm(prompt, provider)).strip()
    try:
        start = raw_selection.index("[")
        end = raw_selection.rindex("]") + 1
        parsed = json.loads(raw_selection[start:end])
        selection = parsed if isinstance(parsed, list) else []
    except (ValueError, json.JSONDecodeError):
        selection = []
    langfuse.update_current_span(output={"selected_specs": selection})
    return selection


async def generate_answer(question: str, chunks: list[dict], provider: str):
    config = get_provider_config(provider)
    prompt = build_prompt(
        question,
        chunks,
        max_evidence_chars=config["max_evidence_chars"],
    )
    return await run_generation(prompt, provider)

# Endpoints

@app.post("/ingest")
@observe(name="ingest")
async def ingest(req: IngestRequest):
    logger.info(f"Ingest request received: {req.specification_url}")
    langfuse.update_current_span(
        input={"url": req.specification_url}
    )
    try:
        specification = fetch_specification(req.specification_url)
        if not specification:
            logger.error("Failed to fetch specification or empty response.")
            raise HTTPException(status_code=400, detail="Invalid or empty specification.")
        specification_name, chunks = _extract_specification_chunks(specification)
        logger.debug(f"Specification name: {specification_name}")
        count = store_chunks(chunks, specification_name)
        if count != len(chunks):
            raise HTTPException(
                status_code=500,
                detail="The API specification could not be saved.",
            )
        logger.info(f"Ingested {count} chunks for {specification_name}.")
        result = {
            "specification_name": specification_name,
            "chunks_stored": count,
            "message": f"Successfully ingested {count} endpoints."
        }
        langfuse.update_current_span(output={
            "specification_name": specification_name,
            "chunks_stored": count
        })
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingest failed: {e}.")
        langfuse.update_current_span(output={"error": str(e)})
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/ingest/file")
@observe(name="ingest-file")
async def ingest_file(file: UploadFile = File(...)):
    filename = file.filename or "uploaded_file"
    logger.info(f"File ingest request received: {filename}")
    langfuse.update_current_span(input={"filename": filename})

    try:
        content = await file.read()

        if not content:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty.",
            )

        extension = filename.lower().rsplit(".", 1)[-1]

        if extension == "json":
            try:
                specification = json.loads(content)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid JSON file.",
                )

            specification_name, chunks = _extract_specification_chunks(
                specification
            )
            item_type = "endpoints"

        elif extension in ("pdf", "txt"):
            try:
                chunks = extract_document_chunks(content, filename)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            specification_name = filename.rsplit(".", 1)[0].strip()
            if not specification_name:
                specification_name = "Uploaded Document"
            item_type = "document chunks"

        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Upload a JSON, PDF, or TXT file.",
            )

        if not chunks:
            raise HTTPException(
                status_code=400,
                detail="No usable content was found in the uploaded file.",
            )

        count = store_chunks(chunks, specification_name)
        if count != len(chunks):
            raise HTTPException(
                status_code=500,
                detail="The uploaded document could not be saved.",
            )

        logger.info(
            f"Ingested {count} {item_type} for {specification_name}."
        )

        result = {
            "specification_name": specification_name,
            "chunks_stored": count,
            "message": f"Successfully ingested {count} {item_type}.",
        }

        langfuse.update_current_span(
            output={
                "specification_name": specification_name,
                "chunks_stored": count,
                "item_type": item_type,
            }
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File ingest failed: {e}")
        langfuse.update_current_span(output={"error": str(e)})
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )

@app.post("/query")
@observe(name="rag-query")
async def query(req: QueryRequest):
    """
    Query pipeline:
      1. Resolve conversational follow-ups into a standalone question.
      2. Decompose compound questions into at most three retrieval tasks.
      3. Hybrid retrieval : BM25 + dense, fused with RRF and re-ranked.
      4. Deduplicate and combine evidence across retrieval tasks.
      5. Query the LLM and score grounding confidence.
      6. If confidence is low, rewrite retrieval and make one corrective attempt.
      7. Return the attempt with the stronger grounding score.
    """
    started_at = time.perf_counter()
    provider = req.llm_provider
    provider_config = get_provider_config(provider)
    reset_llm_metrics()
    logger.info(
        f"Query received for specification: {req.specification_name} "
        f"using {provider_config['label']}"
    )
    # Log the user's question as the trace input — visible at the top level in Langfuse
    langfuse.update_current_span(
        input={
            "question": req.question,
            "specification": req.specification_name,
            "history_length": len(req.history),
            "llm_provider": provider,
        }
    )
    try:
        async def contextualize(question: str, history: list[dict]):
            return await run_query_contextualization(question, history, provider)

        async def route(question: str, specs: list[str]):
            return await run_specification_routing(question, specs, provider)

        async def generate(question: str, chunks: list[dict]):
            return await generate_answer(question, chunks, provider)

        async def rewrite(question: str, answer: str, chunks: list[dict]):
            return await run_query_rewrite(question, answer, chunks, provider)

        async def decompose(question: str):
            return await run_query_decomposition(question, provider)

        history = [
            {"question": turn.question, "answer": turn.answer}
            for turn in req.history
        ]
        available_specs = specification_names()

        def retrieve_selected(question: str, selected_specs: list[str]):
            return retrieve_from_specifications(question, selected_specs)

        result = await run_agent_graph(
            question=req.question,
            history=history,
            specification_name=req.specification_name,
            available_specifications=available_specs,
            contextualize=contextualize,
            route=route,
            retrieve=retrieve_selected,
            generate=generate,
            score=score_confidence,
            rewrite=rewrite,
            decompose=decompose,
            max_chunks=provider_config["max_chunks"],
            workflow_confidence_threshold=60 if provider == "groq" else 70,
            all_specifications_value=ALL_SPECIFICATIONS,
        )
        if not result.chunks:
            logger.warning("No chunks found for query.")
            raise HTTPException(
                status_code=404,
                detail="No specification found with that name. Ingest it first.",
            )
        if not result.answer:
            logger.error("LLM returned empty response.")
            raise HTTPException(status_code=500, detail="LLM failed to generate response.")
        logger.info(
            "Query processed successfully "
            f"(confidence={result.confidence}, attempts={result.attempts}, "
            f"selected_attempt={result.selected_attempt})."
        )
        ordered_source_chunks = order_chunks_by_answer_citations(
            result.answer, result.chunks
        )
        sources = [format_source(chunk) for chunk in ordered_source_chunks]
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        llm = {
            "provider": provider,
            "label": provider_config["label"],
            "model": provider_config["model"],
            "max_chunks": provider_config["max_chunks"],
            "max_evidence_chars": provider_config["max_evidence_chars"],
            **get_llm_metrics(),
        }
        # Log the answer + confidence as the trace output
        langfuse.update_current_span(
            output={
                "answer": result.answer,
                "confidence": result.confidence,
                "sources": sources,
                "llm": llm,
                "latency_ms": elapsed_ms,
                "agent": {
                    "attempts": result.attempts,
                    "retried": result.retried,
                    "selected_attempt": result.selected_attempt,
                    "subqueries": result.subqueries,
                    "resolved_question": result.resolved_question,
                    "selected_specs": result.selected_specs,
                },
            }
        )
        # Confidence as a 0-1 metric — shows up in Langfuse's scores tab and dashboard charts
        langfuse.score_current_trace(name="confidence", value=result.confidence / 100)
        return {
            "answer": result.answer,
            "confidence": result.confidence,
            "sources": sources,
            "llm": llm,
            "latency_ms": elapsed_ms,
            "agent": {
                "attempts": result.attempts,
                "retried": result.retried,
                "selected_attempt": result.selected_attempt,
                "subqueries": result.subqueries,
                "resolved_question": result.resolved_question,
                "selected_specs": result.selected_specs,
            },
        }
    except HTTPException:
        raise
    except LLMProviderError as e:
        logger.error(f"Query provider failed: {e}")
        langfuse.update_current_span(output={"error": str(e), "provider": provider})
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Query failed: {e}")
        langfuse.update_current_span(output={"error": str(e)})
        raise HTTPException(status_code=500, detail="Internal server error")

# List Specifications
@app.get("/llm/providers")
def list_llm_providers():
    return {"providers": provider_catalog()}


@app.get("/specifications")
def list_specs():
    try:
        names = specification_names()
        logger.info(f"Listing {len(names)} specifications.")
        return {"specifications": names}
    except Exception as e:
        logger.error(f"Failed to list specifications: {e}")
        raise HTTPException(status_code=500, detail="Failed to list specifications")

# Transcribe endpoint — not traced, it's infrastructure not RAG pipeline
@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    logger.info(f"Transcribe request received: {file.filename}")
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")
        try:
            api_key = get_provider_api_key("groq")
        except LLMProviderError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("recording.webm", audio_bytes, file.content_type or "audio/webm")},
                data={
                    "model": "whisper-large-v3-turbo",
                    "language": "en",
                    "response_format": "json",
                    "temperature": "0.0",
                },
            )
            response.raise_for_status()
            data = response.json()
        transcript = data.get("text", "").strip()
        if not transcript:
            raise HTTPException(status_code=422, detail="Could not transcribe audio.")
        logger.info(f"Transcribed: '{transcript[:80]}'")
        return {"transcript": transcript}
    except HTTPException:
        raise
    except httpx.TimeoutException as e:
        logger.error("Groq transcription request timed out.")
        raise HTTPException(
            status_code=504,
            detail="Transcription service timed out. Please try again.",
        ) from e
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error(f"Groq transcription API returned HTTP {status}.")
        if status in (401, 403):
            detail = "Groq authentication failed. Check GROQ_API_KEY."
        elif status == 429:
            detail = "Groq rate limit reached. Please try again later."
        else:
            detail = "Transcription service error."
        raise HTTPException(status_code=502, detail=detail) from e
    except httpx.RequestError as e:
        logger.error("Groq transcription request failed.")
        raise HTTPException(
            status_code=502,
            detail="Could not reach the transcription service.",
        ) from e
    except Exception as e:
        logger.error("Transcription failed due to an unexpected error.")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e
