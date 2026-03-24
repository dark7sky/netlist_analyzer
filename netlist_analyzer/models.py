from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .units import numeric_multiplier


@dataclass(slots=True)
class LogicalLine:
    source_line: int
    text: str


@dataclass(slots=True)
class InstanceDef:
    name: str
    category: str
    nodes: list[str]
    ref_name: str
    params: dict[str, str]
    owner_subckt: str
    source_line: int


@dataclass(slots=True)
class SubcktDef:
    name: str
    pins: list[str]
    instances: list[InstanceDef]
    source_line: int


@dataclass(slots=True)
class ParseResult:
    file_path: Path
    top_cell_name: str | None
    subckts: dict[str, SubcktDef]
    warnings: list[str]


@dataclass(slots=True)
class HierarchyNode:
    path: str
    instance_name: str
    ref_name: str
    category: str
    owner_subckt: str
    source_line: int
    children: list["HierarchyNode"] = field(default_factory=list)


@dataclass(slots=True)
class ExpandedOccurrence:
    path: str
    owner_subckt: str
    leaf_name: str
    category: str
    ref_name: str
    params: dict[str, str]
    source_line: int

    @property
    def w(self) -> str:
        return self.params.get("W", "")

    @property
    def l(self) -> str:
        return self.params.get("L", "")

    @property
    def m(self) -> str:
        return self.params.get("M", "")

    @property
    def multiplier(self) -> float:
        return numeric_multiplier(self.params.get("M", ""))

    @property
    def value(self) -> str:
        if self.category == "capacitor":
            return self.params.get("C", self.params.get("VALUE", ""))
        if self.category == "resistor":
            return self.params.get("R", self.params.get("VALUE", ""))
        return self.params.get("VALUE", "")


@dataclass(slots=True)
class SummaryRow:
    summary_scope: str
    owner_subckt: str
    category: str
    ref_name: str
    count: int | float


@dataclass(slots=True)
class SizeBucket:
    owner_subckt: str
    category: str
    ref_name: str
    w: str
    l: str
    value: str
    count: int | float


@dataclass(slots=True)
class AnalysisResult:
    file_path: Path
    top_name: str
    declared_top_name: str | None
    available_tops: list[str]
    hierarchy: HierarchyNode
    expanded_occurrences: list[ExpandedOccurrence]
    expanded_summary: list[SummaryRow]
    local_summary: list[SummaryRow]
    size_buckets: list[SizeBucket]
    warnings: list[str]
