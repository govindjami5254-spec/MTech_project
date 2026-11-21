"""Ground-truth store (M3). Used only by the scorer; never passed to an arm.

The runner gives arms a case directory under ``data.cases_dir``; truth lives under the disjoint
``data.truth_dir`` (enforced by config), so no arm-facing path can reach it.
"""
from __future__ import annotations

import json
from pathlib import Path

from .ingest import resolve_inside
from .schemas import GroundTruth


class TruthStore:
    def __init__(self, truth_dir: str | Path):
        self.root = Path(truth_dir).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"truth directory not found: {self.root}")

    def load(self, case_id: str) -> GroundTruth:
        path = resolve_inside(self.root, f"{case_id}.json")
        truth = GroundTruth.model_validate_json(path.read_text(encoding="utf-8"))
        if truth.case_id != case_id:
            raise ValueError(f"truth file {path.name} contains case {truth.case_id}")
        return truth

    def case_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json") if not p.name.startswith("_"))

    def families(self) -> dict[str, list[str]]:
        """family_id -> case ids (for clustered statistics)."""
        data = json.loads((self.root / "_families.json").read_text(encoding="utf-8"))
        return {fid: info["cases"] for fid, info in data["families"].items()}
