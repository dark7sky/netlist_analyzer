from __future__ import annotations

import re
from pathlib import Path

from .models import InstanceDef, LogicalLine, ParseResult, SubcktDef
from .units import normalize_numeric_params, normalize_spice_number


TOP_CELL_PATTERN = re.compile(r"^\*\s*Top Cell Name:\s*(?P<name>.+?)\s*$", re.IGNORECASE)


def parse_netlist(file_path: str | Path) -> ParseResult:
    path = Path(file_path)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    logical_lines = _build_logical_lines(lines)
    top_cell_name = _find_top_cell(lines)
    warnings: list[str] = []
    subckts: dict[str, SubcktDef] = {}
    current_subckt: SubcktDef | None = None

    for logical_line in logical_lines:
        stripped = logical_line.text.strip()
        if not stripped or stripped.startswith("*"):
            continue

        lowered = stripped.lower()
        if lowered.startswith(".subckt"):
            subckt = _parse_subckt_header(logical_line)
            if subckt.name in subckts:
                warnings.append(
                    f"Duplicate .SUBCKT definition '{subckt.name}' at line {logical_line.source_line}. "
                    "The last definition wins."
                )
            subckts[subckt.name] = subckt
            current_subckt = subckt
            continue

        if lowered.startswith(".ends"):
            current_subckt = None
            continue

        if stripped.startswith("."):
            continue

        if current_subckt is None:
            continue

        instance = _parse_instance(logical_line, subckts)
        if instance is None:
            warnings.append(
                f"Skipped unsupported statement at line {logical_line.source_line}: {logical_line.text.strip()}"
            )
            continue
        instance.owner_subckt = current_subckt.name
        current_subckt.instances.append(instance)

    return ParseResult(
        file_path=path,
        top_cell_name=top_cell_name,
        subckts=subckts,
        warnings=warnings,
    )


def _find_top_cell(lines: list[str]) -> str | None:
    for line in lines:
        match = TOP_CELL_PATTERN.match(line)
        if match:
            return match.group("name").strip()
    return None


def _build_logical_lines(lines: list[str]) -> list[LogicalLine]:
    logical_lines: list[LogicalLine] = []
    current_line_no: int | None = None
    current_parts: list[str] = []

    for line_no, raw_line in enumerate(lines, start=1):
        if current_line_no is None:
            current_line_no = line_no
            current_parts = [raw_line.rstrip()]
            continue

        if raw_line.lstrip().startswith("+"):
            current_parts.append(raw_line.lstrip()[1:].strip())
            continue

        logical_lines.append(LogicalLine(source_line=current_line_no, text=" ".join(current_parts).strip()))
        current_line_no = line_no
        current_parts = [raw_line.rstrip()]

    if current_line_no is not None:
        logical_lines.append(LogicalLine(source_line=current_line_no, text=" ".join(current_parts).strip()))

    return logical_lines


def _parse_subckt_header(logical_line: LogicalLine) -> SubcktDef:
    tokens = logical_line.text.split()
    if len(tokens) < 2:
        raise ValueError(f"Invalid .SUBCKT line at {logical_line.source_line}: {logical_line.text}")
    return SubcktDef(
        name=tokens[1],
        pins=tokens[2:],
        instances=[],
        source_line=logical_line.source_line,
    )


def _parse_instance(logical_line: LogicalLine, known_subckts: dict[str, SubcktDef]) -> InstanceDef | None:
    tokens = logical_line.text.split()
    if not tokens:
        return None

    prefix = tokens[0][0].upper()
    if prefix == "M":
        return _parse_mos(tokens, logical_line.source_line)
    if prefix == "C":
        return _parse_capacitor(tokens, logical_line.source_line)
    if prefix == "R":
        return _parse_resistor(tokens, logical_line.source_line)
    if prefix == "X":
        return _parse_x_instance(tokens, logical_line.source_line, known_subckts)
    return None


def _parse_mos(tokens: list[str], source_line: int) -> InstanceDef:
    if len(tokens) < 6:
        raise ValueError(f"Invalid MOS statement at line {source_line}: {' '.join(tokens)}")
    return InstanceDef(
        name=tokens[0],
        category="mos",
        nodes=tokens[1:5],
        ref_name=tokens[5],
        params=_parse_params(tokens[6:]),
        owner_subckt="",
        source_line=source_line,
    )


def _parse_capacitor(tokens: list[str], source_line: int) -> InstanceDef:
    if len(tokens) < 4:
        raise ValueError(f"Invalid capacitor statement at line {source_line}: {' '.join(tokens)}")
    params: dict[str, str] = {"VALUE": normalize_spice_number(tokens[3])}
    ref_name = "C"
    next_index = 4
    if len(tokens) > 4 and "=" not in tokens[4]:
        ref_name = tokens[4]
        next_index = 5
    params.update(_parse_params(tokens[next_index:]))
    return InstanceDef(
        name=tokens[0],
        category="capacitor",
        nodes=tokens[1:3],
        ref_name=ref_name,
        params=params,
        owner_subckt="",
        source_line=source_line,
    )


def _parse_resistor(tokens: list[str], source_line: int) -> InstanceDef:
    if len(tokens) < 4:
        raise ValueError(f"Invalid resistor statement at line {source_line}: {' '.join(tokens)}")
    normalized_value = normalize_spice_number(tokens[3])
    params: dict[str, str] = {"VALUE": normalized_value, "R": normalized_value}
    ref_name = "R"
    next_index = 4
    if len(tokens) > 4 and "=" not in tokens[4]:
        ref_name = tokens[4]
        next_index = 5
    params.update(_parse_params(tokens[next_index:]))
    return InstanceDef(
        name=tokens[0],
        category="resistor",
        nodes=tokens[1:3],
        ref_name=ref_name,
        params=params,
        owner_subckt="",
        source_line=source_line,
    )


def _parse_x_instance(tokens: list[str], source_line: int, known_subckts: dict[str, SubcktDef]) -> InstanceDef:
    if "/" in tokens:
        slash_index = tokens.index("/")
        ref_name = tokens[slash_index + 1] if slash_index + 1 < len(tokens) else ""
        return InstanceDef(
            name=tokens[0],
            category="subckt",
            nodes=tokens[1:slash_index],
            ref_name=ref_name,
            params=_parse_params(tokens[slash_index + 2 :]),
            owner_subckt="",
            source_line=source_line,
        )

    ref_name = tokens[3] if len(tokens) > 3 else ""
    params = _parse_params(tokens[4:]) if len(tokens) > 4 else {}
    category = _infer_x_primitive_category(tokens[0])
    if ref_name in known_subckts:
        category = "subckt"

    if category == "capacitor" and "C" not in params and "VALUE" not in params:
        params["VALUE"] = normalize_spice_number(ref_name)
    if category == "resistor" and "R" not in params and "VALUE" not in params:
        normalized_value = normalize_spice_number(ref_name)
        params["VALUE"] = normalized_value
        params["R"] = normalized_value

    if category == "subckt":
        return InstanceDef(
            name=tokens[0],
            category=category,
            nodes=tokens[1:-1],
            ref_name=ref_name,
            params=params,
            owner_subckt="",
            source_line=source_line,
        )

    return InstanceDef(
        name=tokens[0],
        category=category,
        nodes=tokens[1:3],
        ref_name=ref_name,
        params=params,
        owner_subckt="",
        source_line=source_line,
    )


def _infer_x_primitive_category(instance_name: str) -> str:
    if len(instance_name) >= 2:
        marker = instance_name[1].upper()
        if marker == "C":
            return "capacitor"
        if marker == "R":
            return "resistor"
        if marker == "M":
            return "mos"
    return "x_primitive"


def _parse_params(tokens: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        params[key.upper()] = value
    return normalize_numeric_params(params)
