from __future__ import annotations

import argparse
from pathlib import Path

from netlist_analyzer.analysis import analyze_netlist, export_analysis, print_terminal_summary
from netlist_analyzer.gui import launch_gui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze hierarchical SPICE/auCdl netlists.")
    parser.add_argument("--file", dest="file_path", help="Netlist file path")
    parser.add_argument("--top", dest="top_name", help="Override top subckt name")
    parser.add_argument("--export", dest="export_dir", help="Export JSON/CSV to this directory and exit")
    parser.add_argument("--no-gui", action="store_true", help="Run analysis in batch mode without opening the GUI")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    file_path = Path(args.file_path).expanduser() if args.file_path else None

    if file_path and not file_path.exists():
        parser.error(f"Netlist file not found: {file_path}")

    if args.export_dir or args.no_gui:
        if not file_path:
            parser.error("--file is required when using --export or --no-gui.")
        result = analyze_netlist(file_path, top_name=args.top_name)
        print_terminal_summary(result)
        if args.export_dir:
            paths = export_analysis(result, args.export_dir)
            print("")
            print("Exported files:")
            for path in paths.values():
                print(f"  {path}")
        return 0

    launch_gui(initial_file=file_path, initial_top=args.top_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
