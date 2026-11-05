import hashlib
import os
import re
import pickle
from pathlib import Path
from typing import Dict, List, Tuple

from rank_bm25 import BM25Okapi
from loggerConfig import get_logger

logger = get_logger("vector_store")

BM25 = Path(__file__).resolve().parent / "bm25_indexes"
LEGACY_BM25_DIRS = (Path(__file__).resolve().parent.parent / "bm25_indexes",)
BM25.mkdir(parents=True, exist_ok=True)


def normalize_name(specification_name: str) -> str:
    """Create a readable, filesystem-safe prefix for a specification name."""
    name = (
        specification_name.lower()
        .strip()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
    )
    name = "".join(c for c in name if c.isalnum() or c == "_")
    name = name.strip("_")[:50]
    if len(name) < 3:
        name += "_api"
    return name


def bm25_path(specification_name: str) -> str:
    digest = hashlib.sha256(
        specification_name.strip().encode("utf-8")
    ).hexdigest()[:16]
    return str(Path(BM25) / f"{normalize_name(specification_name)}-{digest}.pkl")


VALID_DOC_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def sanitize_document_id(document_id: str) -> str:
    """Validate and return safe document_id. Raises ValueError if invalid."""
    if not document_id or not isinstance(document_id, str):
        raise ValueError("A valid non-empty document_id is required.")
    cleaned = document_id.strip()
    if not VALID_DOC_ID_REGEX.match(cleaned):
        raise ValueError("Invalid document_id format. Must match [a-zA-Z0-9_-]{1,64}.")
    return cleaned


def document_bm25_path(document_id: str) -> str:
    """Return the filesystem path for a document-isolated BM25 index."""
    safe_id = sanitize_document_id(document_id)
    return str(Path(BM25) / f"doc_{safe_id}.pkl")


def _legacy_bm25_paths(specification_name: str) -> list[Path]:
    filename = f"{normalize_name(specification_name)}.pkl"
    directories = (Path(BM25), *LEGACY_BM25_DIRS)
    return list(dict.fromkeys(directory / filename for directory in directories))


def tokenize(text: str) -> List[str]:
    """Simple tokenization for BM25 keyword search."""
    return text.lower().split()


def _payload_specification_name(payload: Dict) -> str | None:
    name = payload.get("specification_name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    for chunk in payload.get("chunks", []):
        metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        name = metadata.get("specification_name") if isinstance(metadata, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()

    for chunk in payload.get("chunks", []):
        metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        source_file = metadata.get("source_file") if isinstance(metadata, dict) else None
        if isinstance(source_file, str) and source_file.strip():
            name = Path(source_file).stem.strip()
            if name:
                return name
    return None


def _read_index(path: Path) -> Dict | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with path.open("rb") as index_file:
            payload = pickle.load(index_file)
        if (
            not isinstance(payload, dict)
            or not callable(getattr(payload.get("bm25"), "get_scores", None))
            or not isinstance(payload.get("chunks"), list)
            or any(
                not isinstance(chunk, dict)
                or not isinstance(chunk.get("text"), str)
                for chunk in payload["chunks"]
            )
        ):
            logger.warning(f"Skipping invalid BM25 index '{path.name}'.")
            return None
        return payload
    except Exception as e:
        logger.warning(f"Could not read BM25 index '{path.name}': {e}")
        return None


def store_chunks(
    chunks: List[Dict],
    specification_name: str,
    document_id: str | None = None,
) -> int:
    """
    Store chunks and pre-built BM25 index.
    If document_id is provided, stores an isolated index mapped to document_id.
    Also maintains specification-name lookup for backward compatibility.
    """
    if not chunks:
        logger.warning("No chunks provided for storage.")
        return 0
    if not isinstance(specification_name, str) or not specification_name.strip():
        logger.error("A non-empty specification name is required.")
        return 0
    if any(
        not isinstance(chunk, dict)
        or not isinstance(chunk.get("text"), str)
        or not chunk["text"].strip()
        for chunk in chunks
    ):
        logger.warning("Chunks must contain non-empty text.")
        return 0

    try:
        texts = [c["text"] for c in chunks]
        tokenized = [tokenize(text) for text in texts]
        bm25 = BM25Okapi(tokenized)

        payload = {
            "format_version": 3,
            "document_id": document_id,
            "specification_name": specification_name.strip(),
            "bm25": bm25,
            "chunks": chunks,
        }

        # 1. If document_id is provided, store under document_bm25_path
        if document_id:
            doc_p = Path(document_bm25_path(document_id))
            doc_p.parent.mkdir(parents=True, exist_ok=True)
            temp_doc_p = doc_p.with_suffix(doc_p.suffix + ".tmp")
            with temp_doc_p.open("wb") as index_file:
                pickle.dump(payload, index_file)
            os.replace(temp_doc_p, doc_p)
            logger.info(f"Saved document-isolated BM25 index for document_id='{document_id}'.")

        # 2. Also save to specification path for backward compatibility
        path = Path(bm25_path(specification_name))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        with temporary_path.open("wb") as index_file:
            pickle.dump(payload, index_file)
        os.replace(temporary_path, path)
        logger.info(f"Saved BM25 index for '{specification_name}'.")

        return len(chunks)
    except Exception as e:
        logger.error(f"Failed to save BM25 index: {e}")
        return 0


def list_specifications() -> list[str]:
    """Return original names from valid indexes, including compatible legacy files."""
    names = set()
    directories = (Path(BM25), *LEGACY_BM25_DIRS)
    for directory in dict.fromkeys(directories):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.pkl"):
            if path.name.startswith("doc_"):
                continue
            payload = _read_index(path)
            if payload is None:
                continue
            name = _payload_specification_name(payload)
            if name:
                names.add(name)
            else:
                logger.warning(
                    f"BM25 index '{path.name}' has no recoverable specification name; "
                    "re-ingest its source to list it."
                )
    return sorted(names, key=str.casefold)


def load_bm25(specification_name: str):
    """Return the BM25 index and chunks, or (None, None)."""
    paths = [Path(bm25_path(specification_name)), *_legacy_bm25_paths(specification_name)]
    for path in dict.fromkeys(paths):
        payload = _read_index(path)
        if payload is None:
            continue
        stored_name = _payload_specification_name(payload)
        if not stored_name:
            logger.warning(
                f"BM25 index '{path.name}' has no recoverable specification name; "
                "re-ingest its source."
            )
            continue
        if stored_name.casefold() != specification_name.strip().casefold():
            logger.warning(
                f"Skipping BM25 index '{path.name}' because its stored name does not match."
            )
            continue
        return payload["bm25"], payload["chunks"]

    logger.warning(f"BM25 index not found for '{specification_name}'.")
    return None, None


def load_document_bm25(document_id: str) -> Tuple[BM25Okapi | None, list[dict] | None, str | None]:
    """Return (BM25, chunks, specification_name) for a specific document_id."""
    if not document_id:
        return None, None, None
    try:
        path = Path(document_bm25_path(document_id))
    except ValueError:
        logger.warning(f"Invalid document_id='{document_id}' passed to load_document_bm25.")
        return None, None, None
    payload = _read_index(path)
    if payload is None:
        logger.warning(f"Document BM25 index not found for document_id='{document_id}'.")
        return None, None, None
    return payload["bm25"], payload["chunks"], payload.get("specification_name")


def has_document_index(document_id: str) -> bool:
    """Check if an index exists and is valid for document_id."""
    if not document_id:
        return False
    try:
        path = Path(document_bm25_path(document_id))
    except ValueError:
        return False
    if not path.is_file():
        return False
    return _read_index(path) is not None


def delete_document_index(document_id: str) -> bool:
    """Delete the BM25 index associated with document_id."""
    if not document_id:
        return False
    try:
        path = Path(document_bm25_path(document_id))
    except ValueError:
        return False
    deleted = False
    if path.is_file():
        try:
            path.unlink()
            deleted = True
            logger.info(f"Deleted document index file for document_id='{document_id}'.")
        except Exception as e:
            logger.error(f"Failed to delete index file for document_id='{document_id}': {e}")
    temp_path = path.with_suffix(path.suffix + ".tmp")
    if temp_path.is_file():
        try:
            temp_path.unlink()
        except Exception:
            pass
    return deleted


def rrf_fuse(
    dense_chunks: List[Dict],
    bm25_chunks: List[Dict],
    k: int = 60,
) -> List[Dict]:
    """Fuse ranked lists and avoid duplicate API endpoints."""
    scores: Dict[str, float] = {}
    index: Dict[str, Dict] = {}

    def _key(chunk: Dict) -> str:
        metadata = chunk.get("metadata", {})
        method = metadata.get("method")
        path = metadata.get("path")
        if method and path:
            return f"endpoint:{method}:{path}"
        return f"document:{metadata.get('chunk_id', chunk['text'])}"

    for ranked_chunks in (dense_chunks, bm25_chunks):
        for rank, chunk in enumerate(ranked_chunks):
            key = _key(chunk)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            index[key] = chunk

    ranked_keys = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [index[key] for key in ranked_keys]


def rerank(query: str, chunks: List[Dict], top_n: int = 5) -> List[Dict]:
    """Return the leading BM25 candidates without a transformer reranker."""
    if not chunks:
        return []
    return chunks[:top_n]


def retrieve_hybrid(
    query: str,
    specification_name: str | None = None,
    document_id: str | None = None,
    num_results: int = 20,
    rerank_top_n: int = 5,
) -> List[Dict]:
    """
    BM25 retrieval.
    If document_id is provided, strictly retrieves from that document's isolated index.
    Otherwise, retrieves from specification_name.
    """
    if not query:
        logger.warning("Empty query provided.")
        return []

    if document_id:
        bm25, all_chunks, _ = load_document_bm25(document_id)
        if bm25 is None or not all_chunks:
            logger.warning(f"No document BM25 index available for document_id='{document_id}'.")
            return []
    elif specification_name:
        bm25, all_chunks = load_bm25(specification_name)
        if bm25 is None or not all_chunks:
            logger.warning(f"No BM25 index available for '{specification_name}'.")
            return []
    else:
        logger.warning("Neither document_id nor specification_name provided to retrieve_hybrid.")
        return []

    try:
        scores = bm25.get_scores(tokenize(query))
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:num_results]

        candidates = [all_chunks[i] for i in top_indices]
        return candidates[:rerank_top_n]
    except Exception as e:
        logger.error(f"BM25 retrieval failed: {e}")
        return []
