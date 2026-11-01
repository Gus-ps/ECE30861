"""Upload bodies and download checks (Phase 4 specification sections 5.1, 5.4 and 12).

Uploads are multipart with exactly one part, a binary field named `file`.
Downloads are checked for the required headers and for complete bodies: an
XLSX that opens as a ZIP, or a report that is UTF-8 JSON.
"""

import io
import json
import re
import zipfile
from urllib.parse import unquote

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PART_TYPES = {
    ".xlsx": XLSX,
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
}
GENERATED_SUFFIX = "-remediated.xlsx"
MAX_FILENAME = 255


def upload_files(name, content):
    ##  httpx `files=` for a one-part multipart body. The part's media type follows the
    ##  name only because browsers do the same; the system must not trust it.
    suffix = name[name.rfind("."):].lower() if "." in name else ""
    return {"file": (name, content, PART_TYPES.get(suffix, "application/octet-stream"))}


def generated_name(original):
    ##  Original basename plus -remediated.xlsx, shortened to 255 code points.
    base = original[:-5] if original.lower().endswith(".xlsx") else original
    return base[:MAX_FILENAME - len(GENERATED_SUFFIX)] + GENERATED_SUFFIX


def parse_disposition(value):
    ##  (type, {param: value}) from a Content-Disposition header (RFC 6266); filename*
    ##  is decoded per RFC 8187. Raises ValueError on malformed syntax.
    parts, current, quoted, escaped = [], "", False, False
    for char in value:
        if escaped:
            current, escaped = current + char, False
        elif char == "\\" and quoted:
            current, escaped = current + char, True
        elif char == '"':
            current, quoted = current + char, not quoted
        elif char == ";" and not quoted:
            parts.append(current)
            current = ""
        else:
            current += char
    if quoted:
        raise ValueError("unterminated quoted string")
    parts.append(current)
    kind = parts[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", kind):
        raise ValueError("missing disposition type")
    params = {}
    for part in parts[1:]:
        if not part.strip():
            continue
        name, sep, raw = part.partition("=")
        name, raw = name.strip().lower(), raw.strip()
        if not sep or not name or name in params:
            raise ValueError(f"malformed or repeated parameter {name or part.strip()!r}")
        if name.endswith("*"):
            charset, _, rest = raw.partition("'")
            _, _, encoded = rest.partition("'")
            if charset.lower() != "utf-8" or not encoded:
                raise ValueError(f"{name} must use UTF-8''<percent-encoded> form")
            params[name] = unquote(encoded, encoding="utf-8", errors="strict")
        elif raw.startswith('"'):
            params[name] = re.sub(r"\\(.)", r"\1", raw[1:-1])
        else:
            params[name] = raw
    return kind, params


def download_problems(response, kind, expected_name=None):
    ##  Every way a 200 download breaks the contract; empty when it conforms.
    ##  kind is "workbook" (XLSX) or "report" (JSON audit report).
    problems = []
    headers, body = response.headers, response.body
    media = headers.get("content-type", "").split(";")[0].strip().lower()
    wanted = XLSX if kind == "workbook" else "application/json"
    if media != wanted:
        problems.append(f"Content-Type is {media or 'missing'}, expected {wanted}")
    length = headers.get("content-length")
    if length is None:
        problems.append("Content-Length is missing")
    elif not length.isdigit() or int(length) != len(body):
        problems.append(f"Content-Length {length} does not match the {len(body)} bytes received")
    if headers.get("content-encoding", "identity").lower() != "identity":
        problems.append(f"body is sent with Content-Encoding {headers['content-encoding']}")
    if "no-store" not in [d.strip().lower() for d in headers.get("cache-control", "").split(",")]:
        problems.append("Cache-Control does not include no-store")
    problems += _disposition_problems(headers.get("content-disposition"), expected_name)
    problems += _body_problems(body, kind)
    return problems


def _disposition_problems(value, expected_name):
    if value is None:
        return ["Content-Disposition is missing"]
    try:
        kind, params = parse_disposition(value)
    except ValueError as error:
        return [f"Content-Disposition is malformed ({error})"]
    problems = [] if kind == "attachment" else [f"Content-Disposition type is {kind}, expected attachment"]
    fallback = params.get("filename")
    if not fallback:
        problems.append("Content-Disposition has no filename fallback")
    elif not fallback.isascii() or any(c in fallback for c in '/\\') or any(ord(c) < 32 or ord(c) == 127 for c in fallback):
        problems.append(f"filename fallback {fallback!r} is not a sanitized ASCII name")
    if expected_name is not None:
        if expected_name.isascii():
            shown = params.get("filename*", fallback)
        else:
            shown = params.get("filename*")
            if shown is None:
                problems.append("Content-Disposition lacks filename* for a non-ASCII name")
        if shown is not None and shown != expected_name:
            problems.append(f"download name is {shown!r}, expected {expected_name!r}")
    return problems


def _body_problems(body, kind):
    if kind == "workbook":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as package:
                broken = package.testzip()
        except (zipfile.BadZipFile, ValueError, EOFError, NotImplementedError):
            return ["body is not a complete ZIP package"]
        return [f"ZIP entry {broken} is corrupt"] if broken else []
    try:
        json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ["body is not UTF-8 JSON"]
    return []
