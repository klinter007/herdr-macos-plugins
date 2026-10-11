"""Resolve destinations without shell expansion or a file-extension allowlist."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .common import UserError


@dataclass(frozen=True)
class Destination:
    value: str
    line: int | None = None
    column: int | None = None
    web: bool = False


def unwrap(text):
    """For an explicit selection only; preserve spaces inside each fragment."""
    return "".join(part.strip() for part in text.splitlines()).strip()


def resolve(text, cwd, project=None):
    if len(text) > 8192 or "\x00" in text:
        raise UserError("Invalid or oversized destination.")
    # OSC 8's actual destination wins over the rendered (possibly wrapped) label.
    osc = re.search(r"\x1b\]8;[^;]*;([^\x1b\x07]+)(?:\x07|\x1b\\)", text)
    if osc:
        text = osc.group(1)
    else:
        markdown = re.fullmatch(r"\s*\[[\s\S]*?\]\(([^\x00]+)\)\s*", text)
        if markdown:
            text = markdown.group(1)
    text = text.strip().strip("`\"<>")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise UserError("Control characters are not allowed in destinations.")
    parsed = urlsplit(unwrap(text))
    if parsed.scheme.lower() in ("https", "http"):
        # Real newlines in an unlinked URL are ambiguous; only OSC 8 is authoritative.
        if ("\n" in text or "\r" in text) and not osc:
            raise UserError("This URL contains a real newline. Select its unwrapped hyperlink destination.")
        if not parsed.hostname or any(c.isspace() for c in text):
            raise UserError("Invalid web URL.")
        return Destination(urlunsplit(parsed), web=True)
    if parsed.scheme.lower() == "file":
        if parsed.netloc not in ("", "localhost"):
            raise UserError("Remote file links need a remote file transfer; this action opens local files.")
        text = unquote(parsed.path)
        if parsed.fragment:
            match = re.fullmatch(r"L?(\d+)(?:[:C](\d+))?", parsed.fragment)
            if match:
                text += ":" + ":".join(x for x in match.groups() if x)
    elif parsed.scheme and not re.search(r":\d+(?::\d+)?$", text):
        raise UserError("Only local files and HTTP(S) links are supported.")

    # Try the literal filename first: colons and # can legally be filename characters.
    variants = [(text, None, None)]
    match = re.fullmatch(r"([\s\S]+?)(?::(\d+)(?::(\d+))?|#L(\d+)(?:C(\d+))?)", text)
    if match:
        variants.append((match[1], int(match[2] or match[4]),
                         int(match[3] or match[5]) if match[3] or match[5] else None))
    bases = list(dict.fromkeys(str(Path(p).absolute()) for p in (cwd, project) if p))
    if not bases:
        raise UserError("The source pane's directory is unavailable.")
    for raw, line, column in variants:
        candidates = [raw]
        if "\n" in raw or "\r" in raw:
            candidates.append("".join(raw.splitlines()))
            candidates.append(unwrap(raw))
        for candidate in candidates:
            path = Path(candidate).expanduser()
            hits = []
            for base in bases:
                target = (Path(base) / path).absolute()
                if target.exists() and str(target) not in hits:
                    hits.append(str(target))
                # Pane cwd is authoritative; only fall back when it doesn't exist there.
                if hits:
                    return Destination(hits[0], line, column)
    raise UserError(f"File not found relative to the source pane or project: {unwrap(text)}")


def extract(text, cwd, project=None):
    """Find path-shaped tokens; only explicit wrappers may contain hard wraps."""
    patterns = [r"\[[^\]]*\]\(([^)]+)\)", r"\(([^()]+)\)", r"`([^`]+)`", r'"([^"\n]+)"',
                r"((?:https?://|file://)[^\s<>`]+)", r"([^\s`\"<>]+)"]
    found = []
    seen = set()
    for pattern_index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text[:131072]):
            raw = match[1]
            if raw in seen:
                continue
            seen.add(raw)
            if len(seen) > 1000:
                return found
            if raw in {'.', '..', '/', '~'}:
                continue
            # A literal existing name wins, including legal trailing punctuation.
            for candidate in dict.fromkeys([raw, raw.rstrip(',;.:)!?')]):
                if not candidate or candidate in {'.', '..', '/', '~'}:
                    continue
                parts = [part for part in candidate.split('/') if part]
                if all(part in {'.', '..', '~'} for part in parts):
                    continue
                if pattern_index == len(patterns) - 1 and not (
                        '/' in candidate or re.search(r'[^/.\s]+\.[^/.\s]+', candidate)
                        or re.search(r':\d+(?::\d+)?$', candidate)):
                    continue
                try:
                    item = resolve(candidate, cwd, project)
                    if item not in found:
                        found.append(item)
                    break
                except (UserError, ValueError, OSError):
                    pass
    return found
