import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import fitz
import httpx
from loggerConfig import get_logger

logger = get_logger("ingest")


def is_safe_url(url: str) -> tuple[bool, str]:
    """
    Validate that a URL is safe to fetch and does not point to internal/private networks (SSRF protection).
    Returns (is_safe, error_reason).
    """
    if not isinstance(url, str) or not url.strip():
        return False, "URL cannot be empty."

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "Invalid URL format."

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, "Only HTTP and HTTPS protocols are supported."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must contain a valid hostname."

    lowered_host = hostname.lower().strip("[]")
    if lowered_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"):
        return False, "Access to localhost and internal addresses is forbidden."

    if lowered_host == "169.254.169.254":
        return False, "Access to cloud metadata service is forbidden."

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Could not resolve host '{hostname}'."
    except Exception as e:
        return False, f"Failed to resolve host '{hostname}': {e}"

    if not addr_info:
        return False, f"No IP addresses resolved for host '{hostname}'."

    for _, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False, f"Access to private or internal network address ({ip}) is forbidden."
        except ValueError:
            return False, "Invalid IP address encountered during host resolution."

    return True, ""


# fetching specifications
def fetch_specification(url: str) -> dict:
    is_safe, reason = is_safe_url(url)
    if not is_safe:
        logger.warning(f"SSRF validation blocked request to '{url}': {reason}")
        raise ValueError(reason)

    try:
        logger.info(f"Fetching specification from {url}")
        current_url = url
        response = None
        for _ in range(3):
            response = httpx.get(current_url, timeout=10.0, follow_redirects=False)
            if response.is_redirect:
                redirect_location = response.headers.get("location")
                if not redirect_location:
                    break
                current_url = urljoin(current_url, redirect_location)
                is_safe_redir, redir_reason = is_safe_url(current_url)
                if not is_safe_redir:
                    logger.warning(f"SSRF validation blocked redirect to '{current_url}': {redir_reason}")
                    raise ValueError(f"Redirect blocked: {redir_reason}")
                continue
            break

        if response is None:
            raise ValueError("No response received from specification URL.")

        response.raise_for_status()   # Raises error if: 4xx (client error) or 5xx (server error)
        try:
            data = response.json()
            logger.info("Successfully fetched and parsed JSON.")
            return data
        except json.JSONDecodeError:
            logger.error("Response is not valid JSON.")
            return {}
    except ValueError:
        raise
    except httpx.RequestError as e:
        logger.error(f"Request failed: {e}.")
        return {}
    except httpx.HTTPStatusError as e:
        logger.error(f"Bad HTTP status: {e.response.status_code}.")
        return {}
    
# HTML stripping  
def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# $ref resolution
def resolve_ref(ref: str, specification: dict) -> dict:
    """
    Follow a JSON pointer like #/components/schemas/Foo.
    Returns {} if the path doesn't exist.
    """
    if not ref.startswith("#/"):
        return {}
    parts = ref.lstrip("#/").split("/")
    result = specification
    for part in parts:
        if not isinstance(result, dict):
            return {}
        result = result.get(part, {})
    return result if isinstance(result, dict) else {}

# Schema flattening
def _resolve_schema(schema_obj: dict, specification: dict, _depth: int = 0) -> dict:
    """
    Recursively resolve a schema object into a normalised dict:
        { "required": [...], "properties": { name: { type, description, ... } } }
 
    Handles every common OpenAPI 3.x composition pattern:
        - Direct $ref
        - allOf  (merge all sub-schemas)
        - anyOf / oneOf  (union of all variants - best-effort for docs)
        - Inline properties
        - Nested $ref inside properties
        - additionalProperties
        - Recursive / circular refs (guarded by _depth limit)
    """
    if _depth > 6:
        return {}
    if not isinstance(schema_obj, dict):
        return {}
    # Direct $ref
    if "$ref" in schema_obj:
        resolved = resolve_ref(schema_obj["$ref"], specification)
        return _resolve_schema(resolved, specification, _depth + 1)
    result = {"required": [], "properties": {}}
    # allOf - merge every sub-schema 
    for entry in schema_obj.get("allOf", []):
        sub = _resolve_schema(entry, specification, _depth + 1)
        result["required"] = list(set(result["required"] + sub.get("required", [])))
        result["properties"].update(sub.get("properties", {}))
    # anyOf / oneOf - union of variants (useful for docs)
    for key in ("anyOf", "oneOf"):
        for entry in schema_obj.get(key, []):
            sub = _resolve_schema(entry, specification, _depth + 1)
            # Don't mark required for optional variants
            result["properties"].update(sub.get("properties", {}))
    # Inline properties
    for prop_name, prop_schema in schema_obj.get("properties", {}).items():
        if not isinstance(prop_schema, dict):
            continue
        # Resolve nested $ref inside a property
        if "$ref" in prop_schema:
            resolved_prop = resolve_ref(prop_schema["$ref"], specification)
            prop_schema = {**resolved_prop, **{k: v for k, v in prop_schema.items() if k != "$ref"}}
        result["properties"][prop_name] = {
            "type": prop_schema.get("type", "object" if "properties" in prop_schema else "string"),
            "description": _strip_html(prop_schema.get("description", "")),
            "default": prop_schema.get("default", None),
            "enum": prop_schema.get("enum", None),
            "required": prop_name in schema_obj.get("required", []),
        }
    # Top-level required list
    for req in schema_obj.get("required", []):
        if req not in result["required"]:
            result["required"].append(req)
    return result
 
 
def _extract_content_schema(content: dict, specification: dict) -> dict:
    """
    Pick the best media type from a content dict and resolve its schema.
    Prefers application/json, falls back to the first available type.
    """
    media_type = (
        content.get("application/json") or
        content.get("application/x-www-form-urlencoded") or
        content.get("multipart/form-data") or
        next(iter(content.values()), None)
    )
    if not media_type:
        return {}
    schema_obj = media_type.get("schema", {})
    return _resolve_schema(schema_obj, specification)
 

def _format_resolved_body(schema: dict) -> dict:
    """Convert a resolved schema into the chunk-text format."""
    if not schema or not schema.get("properties"):
        return {}
    return {
        "required_fields": schema.get("required", []),
        "all_fields": {
            name: {k: v for k, v in info.items() if v is not None and v != "" and v != []}
            for name, info in schema.get("properties", {}).items()
        }
    }
 
# Parameter resolution 
def _resolve_parameters(parameters: list, specification: dict) -> list:
    """
    Parameters can be inline or $ref'd from components/parameters.
    Returns a cleaned list with refs resolved.
    """
    resolved = []
    for param in parameters:
        if not isinstance(param, dict):
            continue
        if "$ref" in param:
            param = resolve_ref(param["$ref"], specification)
        if not param:
            continue
        resolved.append({
            "name": param.get("name", ""),
            "in": param.get("in", ""),
            "required": param.get("required", False),
            "description": _strip_html(param.get("description", "")),
            "type": param.get("schema", {}).get("type", "string") if "schema" in param else param.get("type", "string"),
            "enum": param.get("schema", {}).get("enum") or param.get("enum"),
        })
    return resolved
 
# Response summary 
def _summarise_responses(responses: dict, specification: dict) -> dict:
    """
    Extract just the status codes and descriptions - skip the full schemas
    to keep chunk size manageable.
    """
    summary = {}
    for status, resp in responses.items():
        if not isinstance(resp, dict):
            continue
        if "$ref" in resp:
            resp = resolve_ref(resp["$ref"], specification)
        summary[status] = _strip_html(resp.get("description", ""))
    return summary
 
# Chunk extraction
def extract_chunks(specification: dict) -> list[dict]:
    chunks = []
    paths = specification.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        # Path-level parameters (inherited by all operations)
        path_level_params = path_item.get("parameters", [])
        for method, details in path_item.items():
            if method.lower() not in ["get", "post", "put", "patch", "delete", "head", "options"]:
                continue
            if not isinstance(details, dict):
                continue
            try:
                # Merge path-level + operation-level parameters
                operation_params = details.get("parameters", [])
                all_params = path_level_params + operation_params
                resolved_params = _resolve_parameters(all_params, specification)
                # Resolve request body
                request_body = details.get("requestBody", {})
                if "$ref" in request_body:
                    request_body = resolve_ref(request_body["$ref"], specification)
                content = request_body.get("content", {})
                body_schema = _extract_content_schema(content, specification)
                resolved_body = _format_resolved_body(body_schema)
                # Summarise responses
                response_summary = _summarise_responses(
                    details.get("responses", {}), specification
                )
                # Build chunk text
                description = _strip_html(details.get("description", "No description"))
                summary = details.get("summary", "No summary")
                tags = ", ".join(details.get("tags", []))
                synonyms = {
                    "update": "update modify change edit patch",
                    "create": "create add new post",
                    "delete": "delete remove destroy",
                    "retrieve": "retrieve get fetch read",
                    "list": "list search query all",
                }
                action = next((v for k, v in synonyms.items() if k in summary.lower()), "")
                text = (
                    f"{summary} - {method.upper()} {path}\n"
                    f"Operation: {method.upper()} {path}\n"
                    f"Summary: {summary}\n"
                    f"Synonyms: {action}\n"
                    f"Description: {description}\n"
                    f"Parameters: {json.dumps(resolved_params, indent=2)}\n"
                    f"Request Body Fields: {json.dumps(resolved_body, indent=2)}\n"
                    f"Responses: {json.dumps(response_summary, indent=2)}\n"
                    f"Tags: {tags}"
                ).strip()
                chunks.append({
                    "text": text,
                    "metadata": {
                        "path": path,
                        "method": method.upper(),
                        "summary": summary,
                        "specification_name": specification.get("info", {}).get("title", "Unknown API"),
                    }
                })
                logger.debug(f"Processed {method.upper()} {path}.")
            except (TypeError, ValueError) as e:
                logger.error(f"Failed processing {method.upper()} {path}: {e}.")
                continue
    logger.info(f"Extracted {len(chunks)} chunks.")
    return chunks

def extract_document_chunks(
    content: bytes,
    filename: str,
    chunk_size: int = 1500,
    overlap: int = 200,
) -> list[dict]:
    """
    Extract text from a PDF or TXT file and split it into
    overlapping chunks for document retrieval.
    """
    extension = filename.lower().rsplit(".", 1)[-1]

    if extension == "pdf":
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                text = "\n".join(page.get_text() for page in document)
        except Exception as e:
            logger.error(f"Failed to read PDF '{filename}': {e}")
            raise ValueError("Unable to read this PDF file.") from e

    elif extension == "txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise ValueError(
                "Unable to read this TXT file as UTF-8."
            ) from e

    else:
        raise ValueError("Only PDF and TXT files are supported.")

    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        raise ValueError(
            "No extractable text found. The PDF may be scanned or empty."
        )

    chunks = []
    start = 0
    chunk_id = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        # Prefer ending at a word boundary.
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary

        chunk_text = text[start:end].strip()

        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "metadata": {
                    "chunk_id": f"{filename}_{chunk_id}",
                    "source_file": filename,
                    "document_type": extension,
                    "chunk_index": chunk_id,
                },
            })
            chunk_id += 1

        if end >= len(text):
            break

        start = max(end - overlap, start + 1)

    logger.info(
        f"Extracted {len(chunks)} chunks from '{filename}'."
    )
    return chunks

