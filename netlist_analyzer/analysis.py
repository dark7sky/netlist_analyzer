from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .models import (
    AnalysisResult,
    ExpandedOccurrence,
    HierarchyNode,
    ParseResult,
    SizeBucket,
    SubcktDef,
    SummaryRow,
)
from .parser import parse_netlist
from .units import format_count, normalize_search_value, sort_numeric_desc


def analyze_netlist(file_path: str | Path, top_name: str | None = None) -> AnalysisResult:
    parse_result = parse_netlist(file_path)
    return analyze_parse_result(parse_result, top_name=top_name)


def analyze_parse_result(parse_result: ParseResult, top_name: str | None = None) -> AnalysisResult:
    warnings = list(parse_result.warnings)
    available_tops = sorted(parse_result.subckts)
    selected_top = _select_top(parse_result, top_name, warnings)
    top_subckt = parse_result.subckts[selected_top]

    hierarchy_root = HierarchyNode(
        path=selected_top,
        instance_name=selected_top,
        ref_name=selected_top,
        category="top",
        owner_subckt=selected_top,
        source_line=top_subckt.source_line,
        children=[],
    )
    hierarchy_root.children, expanded_occurrences = _expand_hierarchy(
        subckts=parse_result.subckts,
        current_subckt=selected_top,
        path_prefix=selected_top,
        call_stack=[selected_top],
        warnings=warnings,
    )

    return AnalysisResult(
        file_path=parse_result.file_path,
        top_name=selected_top,
        declared_top_name=parse_result.top_cell_name,
        available_tops=available_tops,
        hierarchy=hierarchy_root,
        expanded_occurrences=expanded_occurrences,
        expanded_summary=_build_expanded_summary(expanded_occurrences, selected_top),
        local_summary=_build_local_summary(parse_result),
        size_buckets=_build_size_buckets(expanded_occurrences),
        warnings=warnings,
    )


def filter_occurrences(
    occurrences: list[ExpandedOccurrence],
    category: str = "",
    ref_name: str = "",
    w: str = "",
    l: str = "",
    m: str = "",
    c_value: str = "",
    r_value: str = "",
    text: str = "",
) -> list[ExpandedOccurrence]:
    category = category.strip().lower()
    ref_name = ref_name.strip().lower()
    w = normalize_search_value(w)
    l = normalize_search_value(l)
    m = normalize_search_value(m)
    c_value = normalize_search_value(c_value)
    r_value = normalize_search_value(r_value)
    text = text.strip().lower()

    filtered: list[ExpandedOccurrence] = []
    for occurrence in occurrences:
        if category and occurrence.category.lower() != category:
            continue
        if ref_name and ref_name not in occurrence.ref_name.lower():
            continue
        if w and occurrence.w.lower() != w:
            continue
        if l and occurrence.l.lower() != l:
            continue
        if m and occurrence.m.lower() != m:
            continue
        if c_value:
            cap_value = occurrence.params.get("C", occurrence.params.get("VALUE", "")).lower()
            if occurrence.category != "capacitor" or cap_value != c_value:
                continue
        if r_value:
            resistor_value = occurrence.params.get("R", occurrence.params.get("VALUE", "")).lower()
            if occurrence.category != "resistor" or resistor_value != r_value:
                continue
        if text:
            searchable = " ".join(
                [
                    occurrence.owner_subckt,
                    occurrence.path,
                    occurrence.leaf_name,
                    occurrence.category,
                    occurrence.ref_name,
                    occurrence.value,
                ]
            ).lower()
            if text not in searchable:
                continue
        filtered.append(occurrence)
    return filtered


def export_analysis(result: AnalysisResult, output_dir: str | Path) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    paths = {
        "json": directory / "analysis.json",
        "instances_csv": directory / "instances.csv",
        "subckt_summary_csv": directory / "subckt_summary.csv",
        "size_summary_csv": directory / "size_summary.csv",
    }

    payload = {
        "file_path": str(result.file_path),
        "top_name": result.top_name,
        "available_tops": result.available_tops,
        "warnings": result.warnings,
        "hierarchy": _hierarchy_to_dict(result.hierarchy),
        "expanded_occurrences": [_occurrence_to_dict(item) for item in result.expanded_occurrences],
        "expanded_summary": [asdict(item) for item in result.expanded_summary],
        "local_summary": [asdict(item) for item in result.local_summary],
        "size_buckets": [asdict(item) for item in result.size_buckets],
    }
    paths["json"].write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with paths["instances_csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "owner_subckt",
                "hierarchical_path",
                "instance_name",
                "category",
                "model_or_ref",
                "W",
                "L",
                "M",
                "value",
                "source_line",
            ],
        )
        writer.writeheader()
        for item in result.expanded_occurrences:
            writer.writerow(
                {
                    "owner_subckt": item.owner_subckt,
                    "hierarchical_path": item.path,
                    "instance_name": item.leaf_name,
                    "category": item.category,
                    "model_or_ref": item.ref_name,
                    "W": item.w,
                    "L": item.l,
                    "M": item.m,
                    "value": item.value,
                    "source_line": item.source_line,
                }
            )

    with paths["subckt_summary_csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["summary_scope", "owner_subckt", "category", "model_or_ref", "count"],
        )
        writer.writeheader()
        for item in result.expanded_summary + result.local_summary:
            writer.writerow(
                {
                    "summary_scope": item.summary_scope,
                    "owner_subckt": item.owner_subckt,
                    "category": item.category,
                    "model_or_ref": item.ref_name,
                    "count": format_count(item.count),
                }
            )

    with paths["size_summary_csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["owner_subckt", "category", "model_or_ref", "W", "L", "value", "count"],
        )
        writer.writeheader()
        for item in result.size_buckets:
            writer.writerow(
                {
                    "owner_subckt": item.owner_subckt,
                    "category": item.category,
                    "model_or_ref": item.ref_name,
                    "W": item.w,
                    "L": item.l,
                    "value": item.value,
                    "count": format_count(item.count),
                }
            )

    return paths


def print_terminal_summary(result: AnalysisResult, summary_limit: int = 10) -> None:
    print(f"Analyzed: {result.file_path}")
    print(f"Top cell: {result.top_name}")
    print(f"Expanded occurrences: {len(result.expanded_occurrences)}")
    print(f"Warnings: {len(result.warnings)}")
    print("")
    print("Top expanded counts:")
    for row in result.expanded_summary[:summary_limit]:
        print(f"  {row.category:16} {row.ref_name:20} {format_count(row.count)}")


def _select_top(parse_result: ParseResult, requested_top: str | None, warnings: list[str]) -> str:
    if requested_top and requested_top in parse_result.subckts:
        return requested_top

    if requested_top and requested_top not in parse_result.subckts:
        warnings.append(f"Requested top '{requested_top}' was not found. Falling back to a default top.")

    if parse_result.top_cell_name and parse_result.top_cell_name in parse_result.subckts:
        return parse_result.top_cell_name

    if parse_result.subckts:
        fallback = sorted(parse_result.subckts)[0]
        if parse_result.top_cell_name and parse_result.top_cell_name not in parse_result.subckts:
            warnings.append(
                f"Top Cell Name '{parse_result.top_cell_name}' is not defined as a .SUBCKT. "
                f"Falling back to '{fallback}'."
            )
        return fallback

    raise ValueError("No .SUBCKT definitions were found in the netlist.")


def _expand_hierarchy(
    subckts: dict[str, SubcktDef],
    current_subckt: str,
    path_prefix: str,
    call_stack: list[str],
    warnings: list[str],
) -> tuple[list[HierarchyNode], list[ExpandedOccurrence]]:
    child_nodes: list[HierarchyNode] = []
    occurrences: list[ExpandedOccurrence] = []
    subckt = subckts[current_subckt]

    for instance in subckt.instances:
        node_path = f"{path_prefix}/{instance.name}"
        node = HierarchyNode(
            path=node_path,
            instance_name=instance.name,
            ref_name=instance.ref_name,
            category=instance.category,
            owner_subckt=current_subckt,
            source_line=instance.source_line,
            children=[],
        )

        if instance.category == "subckt":
            if instance.ref_name not in subckts:
                warnings.append(
                    f"Undefined subckt reference '{instance.ref_name}' used by '{instance.name}' "
                    f"in '{current_subckt}' at line {instance.source_line}."
                )
                occurrences.append(
                    ExpandedOccurrence(
                        path=node_path,
                        owner_subckt=current_subckt,
                        leaf_name=instance.name,
                        category="unresolved_subckt",
                        ref_name=instance.ref_name,
                        params={},
                        source_line=instance.source_line,
                    )
                )
                child_nodes.append(node)
                continue

            if instance.ref_name in call_stack:
                warnings.append(
                    f"Recursive hierarchy detected at '{node_path}' referencing '{instance.ref_name}'. "
                    "Expansion stopped for this branch."
                )
                occurrences.append(
                    ExpandedOccurrence(
                        path=node_path,
                        owner_subckt=current_subckt,
                        leaf_name=instance.name,
                        category="recursive_subckt",
                        ref_name=instance.ref_name,
                        params={},
                        source_line=instance.source_line,
                    )
                )
                child_nodes.append(node)
                continue

            nested_nodes, nested_occurrences = _expand_hierarchy(
                subckts=subckts,
                current_subckt=instance.ref_name,
                path_prefix=node_path,
                call_stack=call_stack + [instance.ref_name],
                warnings=warnings,
            )
            node.children = nested_nodes
            child_nodes.append(node)
            occurrences.extend(nested_occurrences)
            continue

        child_nodes.append(node)
        occurrences.append(
            ExpandedOccurrence(
                path=node_path,
                owner_subckt=current_subckt,
                leaf_name=instance.name,
                category=instance.category,
                ref_name=instance.ref_name,
                params=dict(instance.params),
                source_line=instance.source_line,
            )
        )

    return child_nodes, occurrences


def _build_local_summary(parse_result: ParseResult) -> list[SummaryRow]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for owner_subckt, subckt in parse_result.subckts.items():
        for instance in subckt.instances:
            counts[(owner_subckt, instance.category, instance.ref_name)] += 1

    rows = [
        SummaryRow(
            summary_scope="local",
            owner_subckt=owner_subckt,
            category=category,
            ref_name=ref_name,
            count=count,
        )
        for (owner_subckt, category, ref_name), count in counts.items()
    ]
    return sorted(rows, key=lambda item: (item.owner_subckt, item.category, item.ref_name))


def _build_expanded_summary(occurrences: list[ExpandedOccurrence], top_name: str) -> list[SummaryRow]:
    counts: Counter[tuple[str, str]] = Counter()
    for occurrence in occurrences:
        counts[(occurrence.category, occurrence.ref_name)] += 1

    rows = [
        SummaryRow(
            summary_scope="expanded",
            owner_subckt=top_name,
            category=category,
            ref_name=ref_name,
            count=count,
        )
        for (category, ref_name), count in counts.items()
    ]
    return sorted(rows, key=lambda item: (-item.count, item.category, item.ref_name))


def _build_size_buckets(occurrences: list[ExpandedOccurrence]) -> list[SizeBucket]:
    counts: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for occurrence in occurrences:
        counts[
            (
                occurrence.owner_subckt,
                occurrence.category,
                occurrence.ref_name,
                occurrence.w,
                occurrence.l,
                occurrence.value,
            )
        ] += occurrence.multiplier

    rows = [
        SizeBucket(
            owner_subckt=owner_subckt,
            category=category,
            ref_name=ref_name,
            w=w,
            l=l,
            value=value,
            count=_collapse_number(count),
        )
        for (owner_subckt, category, ref_name, w, l, value), count in counts.items()
    ]
    return sorted(
        rows,
        key=lambda item: (
            item.owner_subckt,
            sort_numeric_desc(item.w),
            sort_numeric_desc(item.l),
            item.category,
            item.ref_name,
            item.value,
        ),
    )


def _occurrence_to_dict(occurrence: ExpandedOccurrence) -> dict[str, object]:
    return {
        "path": occurrence.path,
        "owner_subckt": occurrence.owner_subckt,
        "leaf_name": occurrence.leaf_name,
        "category": occurrence.category,
        "ref_name": occurrence.ref_name,
        "params": dict(occurrence.params),
        "source_line": occurrence.source_line,
        "W": occurrence.w,
        "L": occurrence.l,
        "M": occurrence.m,
        "value": occurrence.value,
    }


def _hierarchy_to_dict(node: HierarchyNode) -> dict[str, object]:
    return {
        "path": node.path,
        "instance_name": node.instance_name,
        "ref_name": node.ref_name,
        "category": node.category,
        "owner_subckt": node.owner_subckt,
        "source_line": node.source_line,
        "children": [_hierarchy_to_dict(child) for child in node.children],
    }


def _collapse_number(value: float) -> int | float:
    integer = int(round(value))
    if abs(value - integer) < 1e-9:
        return integer
    return value
