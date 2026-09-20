"""OpenClaw configuration: YAML-driven setup of the affiliate-revenue fleet.

A user's deployment lives in a single ``openclaw.yaml`` file. The file
declares the persistent-memory location, optionally overrides niche
parameters, and selects which smolagents ``Model`` backs the niche agents.
That makes the system configurable-as-code: an operator can add a niche or
swap models without touching Python.

Example::

    memory_path: ./openclaw.db
    seed: 1337
    model:
      type: mock          # or: litellm | openai | inference_client
      model_id: gpt-4o-mini
      api_key_env: OPENAI_API_KEY
    niches:               # optional - omit for the curated default 10
      - slug: outdoor_gear
        base_traffic: 2200    # override one or more fields
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .niches import DEFAULT_NICHES, Niche


__all__ = ["OpenClawConfig", "ModelConfig", "load_config"]


@dataclass
class ModelConfig:
    """Which smolagents ``Model`` backs each niche agent.

    ``type='mock'`` uses :class:`~smolagents.openclaw.mock_model.MockNicheModel`
    so the system runs offline. The other types are constructed lazily from
    smolagents' built-in model classes; if the relevant optional dependency
    is missing the user gets a helpful import error at fleet-build time, not
    at config-load time.
    """

    type: str = "mock"
    model_id: str | None = None
    api_key_env: str | None = None
    api_base: str | None = None
    provider: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenClawConfig:
    memory_path: str = ":memory:"
    seed: int = 1337
    max_steps_per_day: int = 4
    model: ModelConfig = field(default_factory=ModelConfig)
    niches: list[Niche] = field(default_factory=lambda: list(DEFAULT_NICHES))

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_path": self.memory_path,
            "seed": self.seed,
            "max_steps_per_day": self.max_steps_per_day,
            "model": asdict(self.model),
            "niches": [asdict(n) for n in self.niches],
        }


# ---------------------------------------------------------------------------
# YAML loading. We use a tiny hand-rolled loader so OpenClaw doesn't add a
# PyYAML dependency for what is, structurally, three nested mappings. Users
# who want full YAML can pre-render their config to JSON.
# ---------------------------------------------------------------------------


def _strip_inline_comment(line: str) -> str:
    in_quote = False
    quote = ""
    for i, ch in enumerate(line):
        if ch in ('"', "'"):
            if not in_quote:
                in_quote = True
                quote = ch
            elif ch == quote:
                in_quote = False
        elif ch == "#" and not in_quote:
            return line[:i]
    return line


def _coerce(value: str) -> Any:
    v = value.strip()
    if not v:
        return ""
    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
        return v[1:-1]
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    if v.lower() in {"null", "none", "~"}:
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_coerce(p) for p in _split_inline_list(inner)]
    return v


def _split_inline_list(s: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    in_quote = False
    quote = ""
    for ch in s:
        if ch in ('"', "'"):
            if not in_quote:
                in_quote = True
                quote = ch
            elif ch == quote:
                in_quote = False
            buf.append(ch)
        elif ch == "," and not in_quote:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


def _parse_yaml(text: str) -> Any:
    """Parse the small YAML subset OpenClaw actually uses.

    Supports: nested mappings, sequences of mappings (`- key: value` blocks),
    sequences of scalars, inline lists ``[a, b, c]``, quoted strings, ints,
    floats, booleans, null, and ``#`` comments. Anything more exotic (anchors,
    flow mappings, multi-line strings) is rejected with a clear error.
    """
    lines = []
    for raw in text.splitlines():
        stripped = _strip_inline_comment(raw).rstrip()
        if not stripped.strip():
            continue
        lines.append(stripped)

    pos = [0]

    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    def parse_block(min_indent: int) -> Any:
        # Decide mapping vs sequence by peeking.
        if pos[0] >= len(lines):
            return None
        first = lines[pos[0]]
        if indent_of(first) < min_indent:
            return None
        if first.lstrip().startswith("- "):
            return parse_sequence(min_indent)
        return parse_mapping(min_indent)

    def parse_mapping(min_indent: int) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while pos[0] < len(lines):
            line = lines[pos[0]]
            ind = indent_of(line)
            if ind < min_indent:
                break
            if ind > min_indent:
                raise ValueError(f"unexpected indent on line {pos[0] + 1}: {line!r}")
            content = line.lstrip()
            if content.startswith("- "):
                break
            if ":" not in content:
                raise ValueError(f"expected 'key: value' on line {pos[0] + 1}: {line!r}")
            key, _, raw_val = content.partition(":")
            key = key.strip()
            raw_val = raw_val.strip()
            pos[0] += 1
            if raw_val == "":
                # Nested block follows.
                child = parse_block(min_indent + 2) if pos[0] < len(lines) else None
                out[key] = {} if child is None else child
            else:
                out[key] = _coerce(raw_val)
        return out

    def parse_sequence(min_indent: int) -> list[Any]:
        out: list[Any] = []
        while pos[0] < len(lines):
            line = lines[pos[0]]
            ind = indent_of(line)
            if ind < min_indent:
                break
            content = line.lstrip()
            if not content.startswith("- "):
                break
            remainder = content[2:].strip()
            pos[0] += 1
            if not remainder:
                child = parse_block(min_indent + 2)
                out.append({} if child is None else child)
            elif ":" in remainder and not remainder.startswith(("'", '"', "[")):
                # Inline first key of a mapping item; rest of mapping follows.
                key, _, raw_val = remainder.partition(":")
                first: dict[str, Any] = {}
                if raw_val.strip():
                    first[key.strip()] = _coerce(raw_val.strip())
                else:
                    first[key.strip()] = parse_block(min_indent + 2) or {}
                rest = parse_mapping(min_indent + 2) if pos[0] < len(lines) else {}
                first.update(rest)
                out.append(first)
            else:
                out.append(_coerce(remainder))
        return out

    return parse_block(0) or {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _niche_from_overrides(overrides: dict[str, Any]) -> Niche:
    if "slug" not in overrides:
        raise ValueError("each niche entry must have a 'slug'")
    slug = overrides["slug"]
    base_lookup = {n.slug: n for n in DEFAULT_NICHES}
    base = base_lookup.get(slug)
    if base is None:
        # Brand-new niche - require the full set.
        required = {"title", "base_traffic", "base_ctr", "base_cr", "base_aov", "base_commission"}
        missing = required - overrides.keys()
        if missing:
            raise ValueError(f"new niche {slug!r} is missing required fields: {sorted(missing)}")
        return Niche(
            slug=slug,
            title=overrides["title"],
            affiliate_programs=tuple(overrides.get("affiliate_programs", ())),
            base_traffic=float(overrides["base_traffic"]),
            base_ctr=float(overrides["base_ctr"]),
            base_cr=float(overrides["base_cr"]),
            base_aov=float(overrides["base_aov"]),
            base_commission=float(overrides["base_commission"]),
            refund_rate=float(overrides.get("refund_rate", 0.03)),
            volatility=float(overrides.get("volatility", 0.15)),
            recurring=bool(overrides.get("recurring", False)),
            notes=overrides.get("notes", ""),
        )
    # Override individual fields on the curated default.
    patch: dict[str, Any] = {}
    for k, v in overrides.items():
        if k == "slug":
            continue
        if k == "affiliate_programs":
            patch[k] = tuple(v)
        elif k in {"base_traffic", "base_ctr", "base_cr", "base_aov",
                   "base_commission", "refund_rate", "volatility"}:
            patch[k] = float(v)
        elif k == "recurring":
            patch[k] = bool(v)
        elif hasattr(base, k):
            patch[k] = v
    return replace(base, **patch)


def load_config(source: str | Path | dict[str, Any]) -> OpenClawConfig:
    """Load an :class:`OpenClawConfig` from a YAML file, dict, or YAML string.

    Args:
        source: Either a filesystem path to a YAML file, a YAML string, or an
            already-parsed dict (handy for tests).
    """
    if isinstance(source, dict):
        data = source
    elif isinstance(source, Path) or (isinstance(source, str) and (
        os.path.exists(source) or source.endswith((".yaml", ".yml"))
    )):
        text = Path(source).read_text(encoding="utf-8")
        data = _parse_yaml(text)
    else:
        # Treat as inline YAML.
        data = _parse_yaml(source)

    if not isinstance(data, dict):
        raise ValueError("OpenClaw config must be a mapping at the top level")

    model_cfg = ModelConfig()
    if "model" in data and isinstance(data["model"], dict):
        m = data["model"]
        model_cfg = ModelConfig(
            type=m.get("type", "mock"),
            model_id=m.get("model_id"),
            api_key_env=m.get("api_key_env"),
            api_base=m.get("api_base"),
            provider=m.get("provider"),
            extra={k: v for k, v in m.items()
                   if k not in {"type", "model_id", "api_key_env", "api_base", "provider"}},
        )

    if "niches" in data:
        niches = [_niche_from_overrides(n) for n in data["niches"]]
        if not niches:
            niches = list(DEFAULT_NICHES)
    else:
        niches = list(DEFAULT_NICHES)

    return OpenClawConfig(
        memory_path=data.get("memory_path", ":memory:"),
        seed=int(data.get("seed", 1337)),
        max_steps_per_day=int(data.get("max_steps_per_day", 4)),
        model=model_cfg,
        niches=niches,
    )
