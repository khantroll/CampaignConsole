import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple


def strip_markdown_fences(text: str) -> str:
    cleaned = text.strip().replace("\ufeff", "")
    if not cleaned:
        return cleaned

    fenced = re.match(
        r"^```(?:json|JSON)?\s*\r?\n?(.*?)\r?\n?```\s*$",
        cleaned,
        flags=re.DOTALL,
    )
    if fenced:
        return fenced.group(1).strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    return cleaned


def _extract_balanced_json_array(text: str) -> Optional[str]:
    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_balanced_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _load_json_dict(text: str) -> Dict[str, Any]:
    for attempt in (text, _remove_trailing_commas(text)):
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise json.JSONDecodeError("Expected JSON object", attempt, 0)
    raise json.JSONDecodeError("Invalid JSON object", text, 0)


def extract_json_value_for_key(raw: str, key: str) -> Any:
    pattern = re.compile(
        rf'["\']?{re.escape(key)}["\']?\s*:\s*',
        re.IGNORECASE,
    )
    match = pattern.search(raw)
    if not match:
        return None
    snippet = raw[match.end() :].lstrip()
    if not snippet:
        return None
    if snippet[0] == "{":
        extracted = _extract_balanced_json_object(snippet)
        if extracted:
            for loader in (_load_json_dict, parse_python_literal_dict):
                try:
                    return loader(extracted)
                except (json.JSONDecodeError, ValueError, SyntaxError, TypeError):
                    continue
        return None
    if snippet[0] == "[":
        extracted = _extract_balanced_json_array(snippet)
        if extracted:
            for attempt in (extracted, _remove_trailing_commas(extracted)):
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError:
                    try:
                        return ast.literal_eval(attempt)
                    except (ValueError, SyntaxError):
                        continue
        strings = re.findall(r'"((?:\\.|[^"\\])*)"', snippet)
        if strings:
            return [string.replace('\\"', '"') for string in strings if string.strip()]
        return None
    if snippet[0] == '"':
        try:
            value, _ = json.JSONDecoder().raw_decode(snippet)
            return value
        except json.JSONDecodeError:
            pass
    line = snippet.split("\n", 1)[0].strip().rstrip(",")
    if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
        return line[1:-1]
    return None


def parse_llm_json_lenient(
    raw: str,
    *,
    fallback_keys: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    if raw is None or not str(raw).strip():
        raise json.JSONDecodeError("Empty input", "", 0)

    last_error: Optional[Exception] = None
    try:
        return parse_llm_json(raw), None
    except json.JSONDecodeError as exc:
        last_error = exc

    try:
        return parse_python_literal_dict(raw), None
    except (ValueError, SyntaxError, TypeError) as exc:
        if last_error is None:
            last_error = exc

    partial: Dict[str, Any] = {}
    for key in fallback_keys or []:
        value = extract_json_value_for_key(raw, key)
        if value is not None:
            partial[key] = value

    if partial:
        warning = str(last_error) if last_error else "Partial JSON parse"
        return partial, warning

    if isinstance(last_error, json.JSONDecodeError):
        raise last_error
    if last_error is not None:
        raise ValueError(str(last_error))
    raise json.JSONDecodeError("No JSON object found", str(raw), 0)


def parse_llm_json(raw: str) -> Dict[str, Any]:
    if raw is None:
        raise json.JSONDecodeError("Empty input", "", 0)

    candidates = []
    stripped = strip_markdown_fences(str(raw))
    if stripped:
        candidates.append(stripped)

    balanced = _extract_balanced_json_object(stripped or str(raw))
    if balanced and balanced not in candidates:
        candidates.append(balanced)

    loose_start = str(raw).find("{")
    loose_end = str(raw).rfind("}")
    if loose_start != -1 and loose_end > loose_start:
        loose = str(raw)[loose_start : loose_end + 1]
        if loose not in candidates:
            candidates.append(loose)

    last_error: Optional[json.JSONDecodeError] = None
    for candidate in candidates:
        for attempt in (candidate, _remove_trailing_commas(candidate)):
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
            raise json.JSONDecodeError("Expected JSON object", attempt, 0)

    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No JSON object found", str(raw), 0)


def extract_balanced_brace_object(text: str) -> Optional[str]:
    return _extract_balanced_json_object(text)


def parse_python_literal_dict(raw: str) -> Dict[str, Any]:
    if raw is None:
        raise ValueError("Empty input")

    candidates = []
    stripped = strip_markdown_fences(str(raw))
    if stripped:
        candidates.append(stripped)

    balanced = _extract_balanced_json_object(stripped or str(raw))
    if balanced and balanced not in candidates:
        candidates.append(balanced)

    loose_start = str(raw).find("{")
    loose_end = str(raw).rfind("}")
    if loose_start != -1 and loose_end > loose_start:
        loose = str(raw)[loose_start : loose_end + 1]
        if loose not in candidates:
            candidates.append(loose)

    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            parsed = ast.literal_eval(candidate)
        except (ValueError, SyntaxError) as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Expected dict")

    if last_error is not None:
        raise last_error
    raise ValueError("No Python dict found")
