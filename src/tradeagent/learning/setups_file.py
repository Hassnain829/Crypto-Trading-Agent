"""Write a promotion into config/setups.yaml without disturbing the rest of the file.

Only the lines of the changed rules are touched (comments and alignment stay), the promoted challenger's line
is removed from `variants`, and a history comment is added to the header. The result is checked by loading
it again: if the rules are not exactly what was intended, nothing is written.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import yaml

from tradeagent.setups.config import deep_merge

PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_+.-]*$")
YAML_WORDS = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}


def fmt(value: Any) -> str:
    """A YAML flow value in the file's style."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return value if PLAIN.match(value) and value.lower() not in YAML_WORDS else json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json.dumps(v) if isinstance(v, str) else fmt(v) for v in value) + "]"
    raise ValueError(f"cannot write {value!r} into setups.yaml")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(line: str) -> bool:
    return bool(line.strip()) and not line.lstrip().startswith("#")


def _block(lines: list[str], start: int, indent: int) -> int:
    """Index after the block that starts at `start` (lines indented deeper than `indent`)."""
    end = start + 1
    while end < len(lines) and (not _content(lines[end]) or _indent(lines[end]) > indent):
        end += 1
    while end > start + 1 and not _content(lines[end - 1]):
        end -= 1  # trailing blank lines and comments belong to what follows
    return end


def _find(lines: list[str], key: str, indent: int, lo: int, hi: int) -> int | None:
    pattern = re.compile(rf"^ {{{indent}}}{re.escape(key)}:(\s|$)")
    return next((i for i in range(lo, hi) if pattern.match(lines[i])), None)


def _replace(lines: list[str], at: int, key: str, value: Any) -> None:
    """Set the value on line `at`, dropping a block value below it (list items or deeper lines)."""
    indent, end = _indent(lines[at]), at + 1
    while end < len(lines) and _content(lines[end]) and (
            _indent(lines[end]) > indent or (_indent(lines[end]) == indent and lines[end].lstrip().startswith("- "))):
        end += 1
    lines[at:end] = [_set_line(lines[at], key, value)]


def _set_line(line: str, key: str, value: Any) -> str:
    """Replace the value of `key: value  # comment`, keeping the comment where it was."""
    m = re.match(rf"^(\s*{re.escape(key)}:\s*)(.*?)(\s+#.*)?$", line)
    head = f"{m.group(1).rstrip()} {fmt(value)}"
    if not m.group(3):
        return head
    column = len(m.group(1)) + len(m.group(2)) + len(m.group(3)) - len(m.group(3).lstrip())
    return (head.ljust(column) if len(head) < column else head + "  ") + m.group(3).lstrip()


def set_baseline_rule(text: str, path: str, value: Any) -> str:
    lines = text.split("\n")
    top = _find(lines, "baseline", 0, 0, len(lines))
    if top is None:
        raise ValueError("setups.yaml has no baseline section")
    end = _block(lines, top, 0)
    keys = path.split(".")
    if len(keys) == 1:
        at = _find(lines, keys[0], 2, top + 1, end)
        if at is None:
            lines.insert(end, f"  {keys[0]}: {fmt(value)}")
        else:
            _replace(lines, at, keys[0], value)
        return "\n".join(lines)
    section, key = keys
    sec = _find(lines, section, 2, top + 1, end)
    if sec is None:
        lines[end:end] = [f"  {section}:", f"    {key}: {fmt(value)}"]
        return "\n".join(lines)
    sec_end = _block(lines, sec, 2)
    at = _find(lines, key, 4, sec + 1, sec_end)
    if at is None:
        lines.insert(sec_end, f"    {key}: {fmt(value)}")
    else:
        _replace(lines, at, key, value)
    return "\n".join(lines)


def remove_variant(text: str, name: str) -> str:
    lines = text.split("\n")
    top = _find(lines, "variants", 0, 0, len(lines))
    if top is None:
        return text
    at = _find(lines, name, 2, top + 1, _block(lines, top, 0))
    if at is None:
        return text
    del lines[at:_block(lines, at, 2)]
    return "\n".join(lines)


def add_history_note(text: str, note: str) -> str:
    """Add '#   <note>' after the last version line ('#   v...') of the header comment."""
    lines = text.split("\n")
    last = None
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            break
        if re.match(r"^#\s+v\d", line):
            last = i
    if last is not None:
        lines.insert(last + 1, f"#   {note}")
    return "\n".join(lines)


def _paths(change: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    out = []
    for key, value in change.items():
        if isinstance(value, dict):
            out += _paths(value, f"{prefix}{key}.")
        else:
            out.append((f"{prefix}{key}", value))
    return out


def promote_in_file(path: Path, change: dict[str, Any], name: str, note: str, backups: Path) -> Path:
    """Apply `change` to the baseline of setups.yaml, drop variant `name`, add `note`. Returns the backup file."""
    text = path.read_text(encoding="utf-8")
    before = yaml.safe_load(text)
    new = text
    for rule, value in _paths(change):
        new = set_baseline_rule(new, rule, value)
    new = add_history_note(remove_variant(new, name), note)
    after = yaml.safe_load(new)
    expected_variants = {k: v for k, v in (before.get("variants") or {}).items() if k != name}
    if after["baseline"] != deep_merge(before["baseline"], change) or (after.get("variants") or {}) != expected_variants:
        raise ValueError("setups.yaml could not be updated safely (unusual layout); edit it by hand")
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"setups-{time.strftime('%Y%m%d-%H%M%S')}-before-{name}.yaml"
    shutil.copy2(path, backup)
    path.write_text(new, encoding="utf-8")
    return backup
