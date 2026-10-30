def is_endpoint_chunk(metadata: dict) -> bool:
    return bool(metadata.get("method") and metadata.get("path"))


def format_chunk_reference(metadata: dict) -> str:
    if is_endpoint_chunk(metadata):
        return f"{str(metadata['method']).upper()} {metadata['path']}"

    source_file = metadata.get("source_file")
    chunk_index = metadata.get("chunk_index")
    if source_file and isinstance(chunk_index, int) and not isinstance(chunk_index, bool):
        return f"{source_file} (chunk {chunk_index + 1})"
    if source_file:
        return str(source_file)
    return "Uploaded document chunk"


def format_source(chunk: dict) -> dict:
    metadata = chunk.get("metadata", {})
    specification = (
        metadata.get("collection_name")
        or metadata.get("specification_name", "Unknown")
    )

    if is_endpoint_chunk(metadata):
        return {
            "type": "endpoint",
            "endpoint": format_chunk_reference(metadata),
            "summary": metadata.get("summary", ""),
            "specification": specification,
        }

    source_file = metadata.get("source_file", "Uploaded document")
    chunk_index = metadata.get("chunk_index")
    text = " ".join(str(chunk.get("text", "")).split())
    snippet = text[:240]
    if len(text) > len(snippet):
        snippet = f"{snippet.rstrip()}..."

    return {
        "type": "document",
        "source_file": source_file,
        "chunk_index": chunk_index,
        "label": format_chunk_reference(metadata),
        "summary": snippet,
        "specification": specification,
    }
