from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from .analysis import analyze_netlist, export_analysis, filter_occurrences, print_terminal_summary
from .models import AnalysisResult, HierarchyNode, SizeBucket, SummaryRow
from .units import format_count, sort_numeric_desc


class NetlistAnalyzerApp:
    def __init__(self, initial_file: str | Path | None = None, initial_top: str | None = None) -> None:
        self.root = tk.Tk()
        self.root.title("SPICE Netlist Hierarchy Analyzer")
        self.root.geometry("1500x900")

        self.default_font = tkfont.nametofont("TkDefaultFont")
        self.bold_font = self.default_font.copy()
        self.bold_font.configure(weight="bold")

        self.file_var = tk.StringVar(value=str(initial_file) if initial_file else "")
        self.top_var = tk.StringVar(value=initial_top or "")
        self.top_display_var = tk.StringVar(value=initial_top or "Select top")
        self.status_var = tk.StringVar(value="Open a netlist file to begin.")
        self.warning_var = tk.StringVar(value="")
        self.current_top_var = tk.StringVar(value="-")
        self.category_var = tk.StringVar()
        self.ref_var = tk.StringVar()
        self.w_var = tk.StringVar()
        self.l_var = tk.StringVar()
        self.m_var = tk.StringVar()
        self.c_var = tk.StringVar()
        self.r_var = tk.StringVar()
        self.text_var = tk.StringVar()

        self.result: AnalysisResult | None = None

        self._build_ui()
        if initial_file:
            self.load_file(Path(initial_file), requested_top=initial_top)

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.root, padding=8)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Netlist File").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(controls, textvariable=self.file_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Browse", command=self._browse_file).grid(row=0, column=2, padx=4)
        ttk.Button(controls, text="Reload", command=self._reload_current_file).grid(row=0, column=3, padx=4)
        ttk.Label(controls, text="Top").grid(row=0, column=4, sticky="w", padx=(12, 6))
        self.top_button = tk.Menubutton(
            controls,
            textvariable=self.top_display_var,
            font=self.bold_font,
            relief="raised",
            borderwidth=1,
            width=28,
            anchor="w",
        )
        self.top_button.grid(row=0, column=5, sticky="w")
        self.top_menu = tk.Menu(self.top_button, tearoff=False)
        self.top_button.configure(menu=self.top_menu)
        ttk.Button(controls, text="Analyze", command=self._analyze_from_controls).grid(row=0, column=6, padx=4)
        ttk.Button(controls, text="Export", command=self._export_current).grid(row=0, column=7, padx=4)

        ttk.Label(controls, textvariable=self.status_var).grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))
        ttk.Label(controls, textvariable=self.warning_var, foreground="#8B4513", wraplength=1400).grid(
            row=2, column=0, columnspan=8, sticky="w", pady=(2, 0)
        )

        main_pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main_pane.grid(row=1, column=0, sticky="nsew")

        left_frame = ttk.Frame(main_pane, padding=6)
        right_frame = ttk.Frame(main_pane, padding=6)
        main_pane.add(left_frame, weight=1)
        main_pane.add(right_frame, weight=3)

        left_frame.rowconfigure(1, weight=1)
        left_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)
        right_frame.columnconfigure(0, weight=1)

        self._add_top_label(left_frame, row=0)
        self.hierarchy_tree = self._make_treeview(
            left_frame,
            columns=("ref", "category", "line"),
            headings=("Referenced Cell", "Category", "Line"),
            tree_label="Hierarchy",
        )
        self.hierarchy_tree.master.grid(row=1, column=0, sticky="nsew")
        self.hierarchy_tree.column("#0", width=280, stretch=True)
        self.hierarchy_tree.column("ref", width=180, stretch=True)
        self.hierarchy_tree.column("category", width=100, stretch=False)
        self.hierarchy_tree.column("line", width=70, stretch=False, anchor="e")

        right_pane = ttk.Panedwindow(right_frame, orient=tk.VERTICAL)
        right_pane.grid(row=0, column=0, sticky="nsew")

        summary_frame = ttk.Frame(right_pane)
        results_frame = ttk.Frame(right_pane)
        right_pane.add(summary_frame, weight=1)
        right_pane.add(results_frame, weight=1)

        summary_frame.rowconfigure(1, weight=1)
        summary_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(2, weight=1)
        results_frame.columnconfigure(0, weight=1)

        self._add_top_label(summary_frame, row=0)
        summary_notebook = ttk.Notebook(summary_frame)
        summary_notebook.grid(row=1, column=0, sticky="nsew")

        self.expanded_summary_tree = self._make_treeview(
            summary_notebook,
            columns=("ref", "count"),
            headings=("Model/Ref", "Count"),
            tree_label="Top / Category",
        )
        self.local_summary_tree = self._make_treeview(
            summary_notebook,
            columns=("ref", "count"),
            headings=("Model/Ref", "Count"),
            tree_label="Owner / Category",
        )
        self.size_summary_tree = self._make_treeview(
            summary_notebook,
            columns=("count",),
            headings=("Count",),
            tree_label="Category -> Element -> Size -> Subckt",
        )
        summary_notebook.add(self.expanded_summary_tree.master, text="Element types")
        summary_notebook.add(self.local_summary_tree.master, text="Per-Subckt Local Counts")
        summary_notebook.add(self.size_summary_tree.master, text="Size Summary")

        self._add_top_label(results_frame, row=0)
        filter_frame = ttk.LabelFrame(results_frame, text="Filters", padding=8)
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for index in range(6):
            filter_frame.columnconfigure(index, weight=1)

        ttk.Label(filter_frame, text="Category").grid(row=0, column=0, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.category_var).grid(row=1, column=0, sticky="ew", padx=(0, 4))
        ttk.Label(filter_frame, text="Model/Ref").grid(row=0, column=1, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.ref_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Label(filter_frame, text="W").grid(row=0, column=2, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.w_var).grid(row=1, column=2, sticky="ew", padx=4)
        ttk.Label(filter_frame, text="L").grid(row=0, column=3, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.l_var).grid(row=1, column=3, sticky="ew", padx=4)
        ttk.Label(filter_frame, text="M").grid(row=0, column=4, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.m_var).grid(row=1, column=4, sticky="ew", padx=4)
        ttk.Label(filter_frame, text="Path/Subckt Text").grid(row=0, column=5, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.text_var).grid(row=1, column=5, sticky="ew", padx=(4, 0))
        ttk.Label(filter_frame, text="C").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(filter_frame, textvariable=self.c_var).grid(row=3, column=0, sticky="ew", padx=(0, 4))
        ttk.Label(filter_frame, text="R").grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Entry(filter_frame, textvariable=self.r_var).grid(row=3, column=1, sticky="ew", padx=4)
        ttk.Button(filter_frame, text="Apply Filters", command=self._apply_filters).grid(row=3, column=4, sticky="e")
        ttk.Button(filter_frame, text="Clear", command=self._clear_filters).grid(row=3, column=5, sticky="e")

        self.results_tree = self._make_treeview(
            results_frame,
            columns=("owner", "path", "instance", "category", "ref", "w", "l", "m", "value", "line"),
            headings=("Owner Subckt", "Hierarchical Path", "Instance", "Category", "Model/Ref", "W", "L", "M", "Value", "Line"),
        )
        self.results_tree.master.grid(row=2, column=0, sticky="nsew")
        self.results_tree.column("owner", width=140, stretch=False)
        self.results_tree.column("path", width=460, stretch=True)
        self.results_tree.column("instance", width=100, stretch=False)
        self.results_tree.column("category", width=100, stretch=False)
        self.results_tree.column("ref", width=150, stretch=False)
        self.results_tree.column("w", width=80, stretch=False)
        self.results_tree.column("l", width=80, stretch=False)
        self.results_tree.column("m", width=80, stretch=False)
        self.results_tree.column("value", width=100, stretch=False)
        self.results_tree.column("line", width=70, stretch=False, anchor="e")

    def _add_top_label(self, parent: tk.Misc, row: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="w", pady=(0, 6))
        ttk.Label(frame, text="Selected Top:").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.current_top_var, font=self.bold_font).grid(row=0, column=1, sticky="w", padx=(6, 0))

    def _make_treeview(
        self,
        parent: tk.Misc,
        columns: tuple[str, ...],
        headings: tuple[str, ...],
        tree_label: str | None = None,
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        show_mode = "tree headings" if tree_label else "headings"
        tree = ttk.Treeview(frame, columns=columns, show=show_mode)
        if tree_label:
            tree.heading("#0", text=tree_label)
            tree.column("#0", width=220, stretch=True)
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=120, stretch=True)
        tree.tag_configure("bold", font=self.bold_font)
        self._attach_scrollbars(frame, tree)
        return tree

    def _attach_scrollbars(self, parent: tk.Misc, tree: ttk.Treeview) -> None:
        y_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        x_scroll = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

    def _browse_file(self) -> None:
        initial_dir = str(Path(self.file_var.get()).parent) if self.file_var.get() else str(Path.cwd())
        selected = filedialog.askopenfilename(title="Select netlist", initialdir=initial_dir)
        if selected:
            self.load_file(Path(selected))

    def _reload_current_file(self) -> None:
        if not self.file_var.get():
            messagebox.showinfo("No file", "Select a netlist file first.")
            return
        self.load_file(Path(self.file_var.get()), requested_top=self.top_var.get() or None)

    def _select_top_from_menu(self, top_name: str) -> None:
        self.top_var.set(top_name)
        self.top_display_var.set(top_name)
        self._analyze_from_controls()

    def _analyze_from_controls(self) -> None:
        if not self.file_var.get():
            messagebox.showinfo("No file", "Select a netlist file first.")
            return
        self.load_file(Path(self.file_var.get()), requested_top=self.top_var.get() or None)

    def load_file(self, path: Path, requested_top: str | None = None) -> None:
        try:
            self.result = analyze_netlist(path, top_name=requested_top)
        except Exception as exc:
            messagebox.showerror("Analysis failed", str(exc))
            self.status_var.set("Analysis failed.")
            return

        self.file_var.set(str(path))
        self.top_var.set(self.result.top_name)
        self.top_display_var.set(self.result.top_name)
        self.current_top_var.set(self.result.top_name)
        self._refresh_top_menu()

        self.status_var.set(
            f"Loaded {path.name} | top={self.result.top_name} | "
            f"occurrences={len(self.result.expanded_occurrences)} | subckts={len(self.result.available_tops)}"
        )
        if self.result.warnings:
            preview = " | ".join(self.result.warnings[:3])
            if len(self.result.warnings) > 3:
                preview += f" | ... ({len(self.result.warnings)} warnings total)"
            self.warning_var.set(preview)
        else:
            self.warning_var.set("No warnings.")

        self._populate_hierarchy()
        self._populate_summary_tables()
        self._apply_filters()
        print_terminal_summary(self.result)

    def _refresh_top_menu(self) -> None:
        self.top_menu.delete(0, "end")
        if not self.result:
            return

        highlighted = {self.result.top_name}
        if self.result.declared_top_name:
            highlighted.add(self.result.declared_top_name)

        for index, name in enumerate(self.result.available_tops):
            self.top_menu.add_command(label=name, command=lambda target=name: self._select_top_from_menu(target))
            self.top_menu.entryconfigure(index, font=self.bold_font if name in highlighted else self.default_font)

    def _populate_hierarchy(self) -> None:
        self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
        if not self.result:
            return
        self._insert_hierarchy_node("", self.result.hierarchy, is_selected_top=True)

    def _insert_hierarchy_node(self, parent_id: str, node: HierarchyNode, is_selected_top: bool = False) -> None:
        item_id = self.hierarchy_tree.insert(
            parent_id,
            "end",
            text=f"{node.instance_name} : {node.ref_name}",
            values=(node.ref_name, node.category, node.source_line),
            open=True,
            tags=("bold",) if is_selected_top else (),
        )
        for child in node.children:
            self._insert_hierarchy_node(item_id, child)

    def _populate_summary_tables(self) -> None:
        if not self.result:
            return

        self._populate_element_types_tree()
        self._populate_local_summary_tree()
        self._populate_size_summary_tree()

    def _populate_element_types_tree(self) -> None:
        tree = self.expanded_summary_tree
        tree.delete(*tree.get_children())
        if not self.result:
            return

        root_id = tree.insert("", "end", text=self.result.top_name, values=("", ""), open=True, tags=("bold",))
        for row in self.result.expanded_summary:
            tree.insert(root_id, "end", text=row.category, values=(row.ref_name, format_count(row.count)))

    def _populate_local_summary_tree(self) -> None:
        tree = self.local_summary_tree
        tree.delete(*tree.get_children())
        if not self.result:
            return

        grouped: dict[str, list[SummaryRow]] = defaultdict(list)
        for row in self.result.local_summary:
            grouped[row.owner_subckt].append(row)

        for owner in sorted(grouped, key=self._owner_sort_key):
            parent_id = tree.insert(
                "",
                "end",
                text=owner,
                values=("", ""),
                open=True,
                tags=("bold",) if owner == self.result.top_name else (),
            )
            for row in grouped[owner]:
                tree.insert(parent_id, "end", text=row.category, values=(row.ref_name, format_count(row.count)))

    def _populate_size_summary_tree(self) -> None:
        tree = self.size_summary_tree
        tree.delete(*tree.get_children())
        if not self.result:
            return

        grouped: dict[str, list[SizeBucket]] = defaultdict(list)
        for row in self.result.size_buckets:
            grouped[row.category].append(row)

        for category in sorted(grouped):
            category_rows = grouped[category]
            category_count = sum(float(row.count) for row in category_rows)
            category_id = tree.insert(
                "",
                "end",
                text=category,
                values=(format_count(category_count),),
                open=True,
            )

            element_groups: dict[str, list[SizeBucket]] = defaultdict(list)
            for row in category_rows:
                element_groups[row.ref_name].append(row)

            for ref_name in sorted(element_groups):
                element_rows = element_groups[ref_name]
                element_count = sum(float(row.count) for row in element_rows)
                element_id = tree.insert(
                    category_id,
                    "end",
                    text=ref_name,
                    values=(format_count(element_count),),
                    open=True,
                )

                size_groups: dict[tuple[str, str, str], list[SizeBucket]] = defaultdict(list)
                for row in element_rows:
                    size_groups[(row.w, row.l, row.value)].append(row)

                for (w, l, value) in sorted(
                    size_groups,
                    key=lambda item: (sort_numeric_desc(item[0]), sort_numeric_desc(item[1]), item[2]),
                ):
                    size_rows = size_groups[(w, l, value)]
                    size_count = sum(float(row.count) for row in size_rows)
                    size_label_parts = [
                        part for part in [f"W={w}" if w else "", f"L={l}" if l else "", value if value else ""] if part
                    ]
                    size_label = " | ".join(size_label_parts) if size_label_parts else "(default)"
                    size_id = tree.insert(
                        element_id,
                        "end",
                        text=size_label,
                        values=(format_count(size_count),),
                        open=True,
                    )
                    for row in sorted(size_rows, key=lambda item: self._owner_sort_key(item.owner_subckt)):
                        tree.insert(
                            size_id,
                            "end",
                            text=row.owner_subckt,
                            values=(format_count(row.count),),
                            open=True,
                            tags=("bold",) if row.owner_subckt == self.result.top_name else (),
                        )

    def _owner_sort_key(self, owner: str) -> tuple[int, str]:
        if self.result and owner == self.result.top_name:
            return (0, owner)
        return (1, owner)

    def _replace_tree_rows(self, tree: ttk.Treeview, rows: list[tuple[object, ...]]) -> None:
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert("", "end", values=row)

    def _apply_filters(self) -> None:
        if not self.result:
            return
        filtered = filter_occurrences(
            self.result.expanded_occurrences,
            category=self.category_var.get(),
            ref_name=self.ref_var.get(),
            w=self.w_var.get(),
            l=self.l_var.get(),
            m=self.m_var.get(),
            c_value=self.c_var.get(),
            r_value=self.r_var.get(),
            text=self.text_var.get(),
        )
        self._replace_tree_rows(
            self.results_tree,
            [
                (
                    item.owner_subckt,
                    item.path,
                    item.leaf_name,
                    item.category,
                    item.ref_name,
                    item.w,
                    item.l,
                    item.m,
                    item.value,
                    item.source_line,
                )
                for item in filtered
            ],
        )
        self.status_var.set(
            f"Loaded {Path(self.file_var.get()).name} | top={self.result.top_name} | "
            f"filtered={len(filtered)} / total={len(self.result.expanded_occurrences)}"
        )

    def _clear_filters(self) -> None:
        for variable in (
            self.category_var,
            self.ref_var,
            self.w_var,
            self.l_var,
            self.m_var,
            self.c_var,
            self.r_var,
            self.text_var,
        ):
            variable.set("")
        self._apply_filters()

    def _export_current(self) -> None:
        if not self.result:
            messagebox.showinfo("No data", "Analyze a netlist first.")
            return
        initial_dir = str(Path(self.file_var.get()).parent) if self.file_var.get() else str(Path.cwd())
        directory = filedialog.askdirectory(title="Select export directory", initialdir=initial_dir)
        if not directory:
            return
        paths = export_analysis(self.result, directory)
        messagebox.showinfo("Export complete", "Saved:\n" + "\n".join(str(path) for path in paths.values()))


def launch_gui(initial_file: str | Path | None = None, initial_top: str | None = None) -> None:
    app = NetlistAnalyzerApp(initial_file=initial_file, initial_top=initial_top)
    app.run()
