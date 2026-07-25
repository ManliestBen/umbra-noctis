"""Recipes: saved, replayable processing chains.

A recipe is a JSON list of ``{"op": name, "params": {...}}`` steps. Because
every AstroImage records its history in the same format, "save this image's
processing as a recipe" is a one-liner — and any historical result can be
reproduced or tweaked."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..core.image import AstroImage
from ..core.ops import OPS, apply_op


@dataclass
class Recipe:
    name: str
    steps: list = field(default_factory=list)  # [{"op": ..., "params": {...}}]
    description: str = ""

    @classmethod
    def load(cls, path: str | Path) -> Recipe:
        raw = json.loads(Path(path).read_text())
        return cls(name=raw.get("name", Path(path).stem),
                   steps=raw.get("steps", []),
                   description=raw.get("description", ""))

    def save(self, path: str | Path) -> Path:
        Path(path).write_text(json.dumps(
            {"name": self.name, "description": self.description, "steps": self.steps},
            indent=2))
        return Path(path)

    @classmethod
    def from_history(cls, img: AstroImage, name: str = "derived") -> Recipe:
        """Turn an image's processing history into a reusable recipe
        (only steps that are registered ops are kept)."""
        steps = [{"op": h["op"], "params": h.get("params", {})}
                 for h in img.history if h["op"] in OPS]
        return cls(name=name, steps=steps)

    def validate(self) -> list[str]:
        problems = []
        for i, step in enumerate(self.steps):
            if step.get("op") not in OPS:
                problems.append(f"step {i}: unknown op {step.get('op')!r}")
        return problems


def run_recipe(img: AstroImage, recipe: Recipe, progress=None) -> AstroImage:
    """Apply every step of a recipe in order."""
    problems = recipe.validate()
    if problems:
        raise ValueError("Invalid recipe: " + "; ".join(problems))
    current = img
    for i, step in enumerate(recipe.steps):
        current = apply_op(current, step["op"], **step.get("params", {}))
        if progress:
            progress(i + 1, len(recipe.steps), step["op"])
    return current
