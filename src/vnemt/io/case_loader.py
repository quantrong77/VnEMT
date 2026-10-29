"""Read a case YAML file and validate it against the JSON Schema (SPEC-v0.1 section 9.1).

Schema violations are reported in Vietnamese with the dotted key path of the offending
item (SPEC Q-05), e.g. ``circuit.elements[2].R_ohm: giá trị phải > 0``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from vnemt.errors import CaseError


@dataclass(frozen=True)
class CaseFile:
    """A validated case: parsed data plus provenance (SPEC Q-03)."""

    data: dict[str, Any]
    path: Path | None
    sha256: str

    @property
    def name(self) -> str:
        return str(self.data["case"]["name"])


class _Loader(yaml.SafeLoader):
    """Safe YAML loader that also reads ``1e5`` / ``1.0e5`` as floats (YAML 1.2 rule).

    PyYAML follows YAML 1.1, where an exponent without sign is a string; engineers write
    ``R_ohm: 1.0e5`` routinely, so the 1.2 float syntax is added.
    """


_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+]?[0-9]+)?
        |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
        |\.[0-9_]+(?:[eE][-+]?[0-9]+)?
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
        re.VERBOSE,
    ),
    list("-+0123456789."),
)


def load_yaml(text: str) -> Any:
    """Parse YAML text with the VnEMT loader (YAML 1.2 floats)."""
    return yaml.load(text, Loader=_Loader)


@cache
def case_schema() -> dict[str, Any]:
    """Return the case JSON Schema shipped with the package."""
    text = resources.files("vnemt.io.schema").joinpath("case.schema.json").read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def format_path(parts: Iterable[str | int]) -> str:
    """Format a jsonschema path deque as ``a.b[2].c``."""
    out = ""
    for p in parts:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += f".{p}" if out else str(p)
    return out or "(gốc)"


def _translate(err: ValidationError) -> str:
    """Translate one jsonschema error into a Vietnamese message."""
    v = err.validator
    val: Any = err.validator_value
    inst: Any = err.instance
    schema: Any = err.schema
    if v == "required":
        missing = [k for k in val if isinstance(inst, dict) and k not in inst]
        return "thiếu khóa bắt buộc " + ", ".join(f"'{k}'" for k in missing)
    if v == "additionalProperties":
        allowed = set(schema.get("properties", {}))
        extra = sorted(k for k in inst if k not in allowed) if isinstance(inst, dict) else []
        return "khóa không được hỗ trợ " + ", ".join(f"'{k}'" for k in extra)
    if v == "type":
        return f"kiểu dữ liệu phải là {val}, nhận được {inst!r}"
    if v == "enum":
        return f"giá trị {inst!r} không hợp lệ; chọn một trong {list(val)}"
    if v == "const":
        return f"giá trị phải là {val!r}"
    if v == "minimum":
        return f"giá trị phải ≥ {val}, nhận được {inst}"
    if v == "maximum":
        return f"giá trị phải ≤ {val}, nhận được {inst}"
    if v == "exclusiveMinimum":
        return f"giá trị phải > {val}, nhận được {inst}"
    if v == "exclusiveMaximum":
        return f"giá trị phải < {val}, nhận được {inst}"
    if v == "pattern":
        return f"chuỗi {inst!r} không đúng mẫu {val}"
    if v == "minItems":
        return f"cần ít nhất {val} phần tử"
    if v == "maxItems":
        return f"tối đa {val} phần tử"
    if v == "minLength":
        return "chuỗi không được rỗng"
    if v == "oneOf":
        return f"giá trị {inst!r} không khớp dạng cho phép nào"
    return err.message


def schema_errors(data: Any) -> list[str]:
    """Return all schema violations of ``data`` as Vietnamese messages, sorted by key path."""
    validator = Draft202012Validator(case_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{format_path(e.absolute_path)}: {_translate(e)}" for e in errors]


def _semantic_errors(data: dict[str, Any]) -> list[str]:
    """Checks that JSON Schema cannot express (unique ids...)."""
    msgs: list[str] = []
    seen: dict[str, int] = {}
    for i, el in enumerate(data.get("circuit", {}).get("elements", [])):
        eid = el.get("id")
        if eid in seen:
            msgs.append(f"circuit.elements[{i}].id: trùng mã '{eid}' với elements[{seen[eid]}]")
        else:
            seen[eid] = i
        nodes = el.get("nodes", [])
        if len(nodes) == 2 and nodes[0] == nodes[1]:
            msgs.append(f"circuit.elements[{i}].nodes: hai đầu trùng nút '{nodes[0]}'")
    return msgs


def parse_case(text: str, path: Path | None = None) -> CaseFile:
    """Parse and validate case text. Raises :class:`CaseError` listing every problem."""
    src = str(path) if path else None
    try:
        data = load_yaml(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"dòng {mark.line + 1}, cột {mark.column + 1}" if mark else None
        raise CaseError(f"lỗi cú pháp YAML: {exc}", path=where, source=src) from exc
    if not isinstance(data, dict):
        raise CaseError("file case phải là một đối tượng YAML (khóa: giá trị)", source=src)
    msgs = schema_errors(data)
    if not msgs:
        msgs = _semantic_errors(data)
    if msgs:
        raise CaseError("case không hợp lệ:\n  - " + "\n  - ".join(msgs), source=src)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return CaseFile(data=data, path=path, sha256=digest)


def load_case(path: str | Path) -> CaseFile:
    """Read and validate a case file from disk."""
    p = Path(path)
    if not p.is_file():
        raise CaseError("không tìm thấy file case", source=str(p))
    return parse_case(p.read_text(encoding="utf-8"), path=p)
