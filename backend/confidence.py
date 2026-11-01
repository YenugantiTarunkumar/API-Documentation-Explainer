import json
import math
import re
from collections import Counter
from typing import List, Dict

from loggerConfig import get_logger
from workflow_confidence import score_workflow_confidence

logger = get_logger("confidence")

# Internal helpers
def _cosine_score(answer: str, chunks: List[Dict]) -> float:
    """Return the best term-frequency cosine similarity without a model."""
    answer_terms = Counter(re.findall(r"[a-z0-9_]+", answer.lower()))
    answer_norm = math.sqrt(sum(count * count for count in answer_terms.values()))
    if not answer_norm:
        return 0.0

    best_score = 0.0
    for chunk in chunks:
        chunk_terms = Counter(
            re.findall(r"[a-z0-9_]+", chunk.get("text", "").lower())
        )
        chunk_norm = math.sqrt(sum(count * count for count in chunk_terms.values()))
        if not chunk_norm:
            continue
        dot_product = sum(
            count * chunk_terms.get(term, 0)
            for term, count in answer_terms.items()
        )
        best_score = max(best_score, dot_product / (answer_norm * chunk_norm))
    return best_score

def _extract_known_fields(chunks: List[Dict]) -> set:
    """
    Parse the resolved schema fields that were baked into chunk text at
    ingest time. Looks for the 'all_fields' section in each chunk.
    """
    known = set()
    for chunk in chunks:
        text = chunk.get("text", "")
        # Find the Request Body Fields JSON block
        match = re.search(r"Request Body Fields:\s*(\{.*?\})\s*(?:Responses:|Tags:|$)", 
                         text, re.DOTALL)
        if not match:
            continue
        try:
            body = json.loads(match.group(1))
            known.update(body.get("required_fields", []))
            known.update(body.get("all_fields", {}).keys())
        except json.JSONDecodeError:
            continue
    return known

def _flatten_keys(obj, prefix="") -> list:
    """Recursively extract all keys from a nested dict."""
    keys = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(k)
            keys.extend(_flatten_keys(v, prefix=k))
    return keys

def _verify_json_examples(answer: str, chunks: List[Dict]) -> float:
    known_fields = _extract_known_fields(chunks)
    if not known_fields:
        return 1.0  # no schema info available, don't penalise
    code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", answer)
    if not code_blocks:
        return 1.0
    total, grounded = 0, 0
    for block in code_blocks:
        try:
            obj = json.loads(block.strip())
            for field in _flatten_keys(obj):
                total += 1
                if field in known_fields:
                    grounded += 1
        except json.JSONDecodeError:
            continue
    return grounded / total if total > 0 else 1.0

def _grounding_confidence(answer: str, chunks: List[Dict]) -> int:
    lexical_score = _cosine_score(answer, chunks)
    json_score = _verify_json_examples(answer, chunks)
    combined = 0.7 * lexical_score + 0.3 * json_score
    confidence = round(combined * 100)
    logger.info(
        f"Confidence (lexical={lexical_score:.2f}, "
        f"JSON field grounding={json_score:.2f}, combined={combined:.2f}): "
        f"{confidence}/100"
    )
    return confidence

# Public scorer
def score_confidence(query: str, answer: str, chunks: List[Dict]) -> int:
    """
    Low-memory confidence score (0–100) using token overlap and JSON fields.

    This is a lightweight lexical estimate, not a semantic or model-based judge.
    """
    if not answer:
        logger.warning("Empty answer provided.")
        return 0
    if not chunks:
        logger.warning("No chunks provided for confidence scoring.")
        return 0
    workflow = score_workflow_confidence(answer, chunks, _grounding_confidence)
    if workflow is not None:
        logger.info(
            "Workflow confidence "
            f"(steps={workflow.step_scores}, "
            f"coverage={workflow.answered_steps}/{workflow.expected_steps}, "
            f"combined={workflow.score}/100)"
        )
        return workflow.score
    return _grounding_confidence(answer, chunks)


score_confidence.includes_workflow_completeness = True
