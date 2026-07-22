"""Operation registry.

Every processing operation in Umbra Noctis registers itself here with a name,
a human label, a pipeline stage, and a parameter specification. The registry
is the single source of truth used by:

- the CLI (``umbra process --op <name> ...``),
- the recipe runner (recipes are just JSON lists of registry calls),
- the GUI (tool panels are generated from parameter specs),
- the docs generator (``umbra ops --markdown``).

An operation is a pure function ``func(AstroImage, **params) -> AstroImage``.
``apply_op`` wraps it: validates parameters, calls it, and appends the history
record — so history/reproducibility can never be forgotten by an op author.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .image import AstroImage


@dataclass
class Param:
    name: str
    kind: str = "float"          # float | int | bool | choice | str
    default: object = None
    lo: float | None = None      # slider bounds for numeric params
    hi: float | None = None
    doc: str = ""
    choices: tuple = ()


@dataclass
class OpSpec:
    name: str
    func: Callable
    label: str
    stage: str                   # calibrate | linear | stretch | nonlinear | geometry | cosmetic
    doc: str
    params: list = field(default_factory=list)

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)


OPS: dict[str, OpSpec] = {}


def register_op(name: str, label: str, stage: str, params: list[Param] | None = None):
    """Decorator: register a processing operation."""

    def deco(func: Callable) -> Callable:
        OPS[name] = OpSpec(
            name=name,
            func=func,
            label=label,
            stage=stage,
            doc=(func.__doc__ or "").strip(),
            params=params or [],
        )
        return func

    return deco


def coerce_params(spec: OpSpec, params: dict) -> dict:
    """Validate/coerce user-supplied params against the spec; fill defaults."""
    out = {}
    for p in spec.params:
        val = params.get(p.name, p.default)
        if val is None:
            continue
        if p.kind == "float":
            val = float(val)
            if p.lo is not None:
                val = max(p.lo, min(p.hi if p.hi is not None else val, val))
        elif p.kind == "int":
            val = int(val)
        elif p.kind == "bool":
            val = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes", "on")
        elif p.kind == "choice":
            val = str(val)
            if p.choices and val not in p.choices:
                raise ValueError(f"{spec.name}: {p.name} must be one of {p.choices}, got {val!r}")
        out[p.name] = val
    unknown = set(params) - {p.name for p in spec.params}
    if unknown:
        raise ValueError(f"{spec.name}: unknown parameter(s) {sorted(unknown)}")
    return out


def apply_op(img: AstroImage, name: str, **params) -> AstroImage:
    """Apply a registered operation and record it in the image history."""
    if name not in OPS:
        raise KeyError(f"Unknown operation {name!r}. Known: {sorted(OPS)}")
    spec = OPS[name]
    clean = coerce_params(spec, params)
    result = spec.func(img, **clean)
    result.record(name, clean)
    return result


def ops_markdown() -> str:
    """Render the full operation reference as Markdown (used by docs/CLI)."""
    lines = ["# Operation Reference", ""]
    by_stage: dict[str, list[OpSpec]] = {}
    for spec in OPS.values():
        by_stage.setdefault(spec.stage, []).append(spec)
    for stage in ("calibrate", "linear", "stretch", "nonlinear", "geometry", "cosmetic"):
        specs = sorted(by_stage.get(stage, []), key=lambda s: s.name)
        if not specs:
            continue
        lines += [f"## Stage: {stage}", ""]
        for s in specs:
            lines += [f"### `{s.name}` — {s.label}", "", s.doc, ""]
            if s.params:
                lines += ["| Parameter | Type | Default | Range | Description |",
                          "|---|---|---|---|---|"]
                for p in s.params:
                    rng = ""
                    if p.lo is not None or p.hi is not None:
                        rng = f"{p.lo}–{p.hi}"
                    elif p.choices:
                        rng = ", ".join(p.choices)
                    lines.append(f"| `{p.name}` | {p.kind} | {p.default} | {rng} | {p.doc} |")
                lines.append("")
    return "\n".join(lines)
