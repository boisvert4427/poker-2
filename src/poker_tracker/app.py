from __future__ import annotations

import tkinter as tk
import json
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageEnhance, ImageTk

from .config import DEFAULT_CALIBRATION, load_calibration, save_calibration
from .detection import (
    HistoryLocation,
    WinamaxProcess,
    WinamaxWindow,
    list_winamax_windows,
    select_preferred_table_window,
    summarize_detection,
)
from .history import read_history_text
from .live_state import build_live_snapshot, format_live_snapshot
from .ocr import OcrSnapshot, capture_window, run_local_ocr
from .parser import ParsedHand, parse_winamax_hand
from .session_recorder import SessionRecorder


ROOT_DIR = Path(__file__).resolve().parents[2]


class PokerTrackerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Winamax Poker Tracker Prototype")
        self.root.geometry("1680x980")

        self.status_var = tk.StringVar(value="Pret pour le premier scan.")
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.refresh_ms = 5000
        self._after_id: str | None = None
        self._record_after_id: str | None = None
        self.calibration_entries: dict[str, list[tk.StringVar]] = {}
        self.calibration_preview_label: tk.Label | None = None
        self.calibration_preview_image: ImageTk.PhotoImage | None = None
        self.last_detected_window: WinamaxWindow | None = None
        self.last_preview_source_path: str | None = None
        self.session_recorder = SessionRecorder(ROOT_DIR / "sessions")
        self.recording_session_var = tk.StringVar(value="Aucune session de capture.")
        self.record_interval_ms = 5000
        self.is_recording = False
        self.review_image_label: tk.Label | None = None
        self.review_image_tk: ImageTk.PhotoImage | None = None
        self.review_text: tk.Text | None = None
        self.review_snapshots: list[dict] = []
        self.review_index = 0

        self._build_layout()
        self.refresh()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(
            header,
            text="Prototype de detection Winamax",
            font=("Segoe UI", 18, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            header,
            text="Scan des processus, fenetres Windows et dossiers d'historiques.",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        refresh_button = ttk.Button(header, text="Rafraichir", command=self.refresh)
        refresh_button.grid(row=0, column=1, rowspan=2, padx=(12, 0))

        auto_refresh = ttk.Checkbutton(
            header,
            text="Auto-refresh",
            variable=self.auto_refresh_var,
            command=self._toggle_auto_refresh,
        )
        auto_refresh.grid(row=0, column=2, rowspan=2, padx=(12, 0))

        record_button = ttk.Button(header, text="Nouvelle session", command=self._start_recording_session)
        record_button.grid(row=0, column=3, rowspan=2, padx=(12, 0))

        snapshot_button = ttk.Button(header, text="Capturer snapshot", command=self._record_snapshot)
        snapshot_button.grid(row=0, column=4, rowspan=2, padx=(12, 0))

        start_record_button = ttk.Button(header, text="Start recording", command=self._start_auto_recording)
        start_record_button.grid(row=0, column=5, rowspan=2, padx=(12, 0))

        stop_record_button = ttk.Button(header, text="Stop recording", command=self._stop_auto_recording)
        stop_record_button.grid(row=0, column=6, rowspan=2, padx=(12, 0))

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))

        self.processes_tree = self._create_tree(
            notebook,
            "Processus Winamax",
            ("pid", "name", "window_title", "executable"),
            ("PID", "Nom", "Titre principal", "Executable"),
        )
        self.windows_tree = self._create_tree(
            notebook,
            "Fenetres detectees",
            ("hwnd", "pid", "title", "visible", "rect"),
            ("HWND", "PID", "Titre", "Visible", "Rectangle"),
        )
        self.histories_tree = self._create_tree(
            notebook,
            "Dossiers d'historiques",
            ("path", "source", "exists", "accessible", "details"),
            ("Chemin", "Source", "Existe", "Accessible", "Details"),
        )
        self.hand_text = self._create_text_tab(notebook, "Derniere main")
        self.live_text = self._create_text_tab(notebook, "Main en cours")
        self.ocr_text = self._create_text_tab(notebook, "OCR live")
        self._create_calibration_tab(notebook)
        self._create_review_tab(notebook)

        footer = ttk.Frame(self.root, padding=(16, 0, 16, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.recording_session_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _create_tree(
        self,
        notebook: ttk.Notebook,
        tab_name: str,
        columns: tuple[str, ...],
        headings: tuple[str, ...],
    ) -> ttk.Treeview:
        frame = ttk.Frame(notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        notebook.add(frame, text=tab_name)

        tree = ttk.Treeview(frame, columns=columns, show="headings")
        tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        for column, heading in zip(columns, headings, strict=True):
            tree.heading(column, text=heading)
            width = 130 if column not in {"title", "window_title", "executable", "path", "details"} else 260
            tree.column(column, width=width, anchor="w")

        return tree

    def _create_text_tab(self, notebook: ttk.Notebook, tab_name: str) -> tk.Text:
        frame = ttk.Frame(notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        notebook.add(frame, text=tab_name)

        text = tk.Text(frame, wrap="word", font=("Consolas", 10))
        text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        text.configure(state="disabled")
        return text

    def _create_calibration_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        frame.columnconfigure(0, weight=0)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        notebook.add(frame, text="Calibration")

        ttk.Label(
            frame,
            text="Zones relatives de la table Winamax (left, top, right, bottom).",
        ).grid(row=0, column=0, sticky="w")

        grid = ttk.Frame(frame)
        grid.grid(row=1, column=0, sticky="nw", pady=(10, 10))

        calibration = load_calibration()
        zones = calibration.get("zones", {})
        headers = ("Zone", "Left", "Top", "Right", "Bottom")
        for col, header in enumerate(headers):
            ttk.Label(grid, text=header).grid(row=0, column=col, padx=4, pady=2, sticky="w")

        for row, (name, values) in enumerate(zones.items(), start=1):
            ttk.Label(grid, text=name).grid(row=row, column=0, padx=4, pady=2, sticky="w")
            vars_for_zone: list[tk.StringVar] = []
            for col, value in enumerate(values, start=1):
                var = tk.StringVar(value=f"{value:.2f}")
                entry = ttk.Entry(grid, textvariable=var, width=8)
                entry.grid(row=row, column=col, padx=4, pady=2, sticky="w")
                vars_for_zone.append(var)
            self.calibration_entries[name] = vars_for_zone

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="w")
        ttk.Button(buttons, text="Enregistrer calibration", command=self._save_calibration).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(buttons, text="Recharger valeurs", command=self._reload_calibration).grid(row=0, column=1)
        ttk.Button(buttons, text="Reset defaut", command=self._reset_calibration_defaults).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(buttons, text="Appliquer blocs", command=self._redraw_calibration_preview).grid(
            row=0, column=3, padx=(8, 0)
        )
        ttk.Button(buttons, text="Rafraichir preview", command=self._refresh_calibration_preview).grid(
            row=0, column=4, padx=(8, 0)
        )

        preview_frame = ttk.Frame(frame)
        preview_frame.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(20, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        ttk.Label(preview_frame, text="Preview calibration").grid(row=0, column=0, sticky="w")
        self.calibration_preview_label = tk.Label(
            preview_frame,
            text="Aucune capture disponible.",
            anchor="center",
            bg="#1f1f1f",
            fg="#f2f2f2",
            relief="sunken",
            bd=1,
        )
        self.calibration_preview_label.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    def _create_review_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        notebook.add(frame, text="Review")

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Button(controls, text="Charger derniere session", command=self._load_latest_session_review).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(controls, text="Snapshot precedent", command=lambda: self._move_review(-1)).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(controls, text="Snapshot suivant", command=lambda: self._move_review(1)).grid(
            row=0, column=2, padx=(0, 8)
        )

        self.review_image_label = tk.Label(
            frame,
            text="Aucune session chargee.",
            anchor="center",
            bg="#1f1f1f",
            fg="#f2f2f2",
            relief="sunken",
            bd=1,
        )
        self.review_image_label.grid(row=1, column=0, sticky="nsew", padx=(0, 12))

        self.review_text = tk.Text(frame, wrap="word", font=("Consolas", 10))
        self.review_text.grid(row=1, column=1, sticky="nsew")
        self.review_text.configure(state="disabled")

    def refresh(self) -> None:
        detection = summarize_detection()
        self.last_detected_window = detection["active_table_window"]
        self._fill_processes(detection["processes"])
        self._fill_windows(detection["windows"])
        self._fill_histories(detection["history_locations"])
        self._fill_latest_hand(detection["latest_history_file"])
        ocr_snapshot = self._fill_ocr(detection["active_table_window"])
        self._fill_live_state(detection["latest_history_file"], detection["active_table_window"], ocr_snapshot)
        if self.calibration_preview_image is None:
            self._refresh_calibration_preview()

        process_count = len(detection["processes"])
        window_count = len(detection["windows"])
        history_count = len(detection["history_locations"])
        self.status_var.set(
            f"Scan termine: {process_count} processus, {window_count} fenetres, {history_count} emplacements historiques."
        )
        self._schedule_refresh()

    def _fill_processes(self, rows: list[WinamaxProcess]) -> None:
        self._clear_tree(self.processes_tree)
        for row in rows:
            self.processes_tree.insert(
                "",
                "end",
                values=(row.pid, row.name, row.window_title or "-", row.executable or "-"),
            )

    def _fill_windows(self, rows: list[WinamaxWindow]) -> None:
        self._clear_tree(self.windows_tree)
        for row in rows:
            self.windows_tree.insert(
                "",
                "end",
                values=(row.hwnd, row.pid, row.title, "oui" if row.visible else "non", row.rect),
            )

    def _fill_histories(self, rows: list[HistoryLocation]) -> None:
        self._clear_tree(self.histories_tree)
        for row in rows:
            self.histories_tree.insert(
                "",
                "end",
                values=(
                    row.path,
                    row.source,
                    "oui" if row.exists else "non",
                    "oui" if row.accessible else "non",
                    row.details,
                ),
            )

    def _fill_latest_hand(self, history_file: object) -> None:
        if history_file is None:
            self._set_hand_text("Aucun fichier d'historique detecte.")
            return

        raw_text = read_history_text(history_file.path)
        parsed = parse_winamax_hand(raw_text)
        self._set_hand_text(self._format_hand(parsed, history_file.path))

    def _fill_ocr(self, window: object) -> OcrSnapshot | None:
        if window is None:
            self._set_ocr_text("Aucune fenetre de table Winamax active detectee.")
            return None

        snapshot = run_local_ocr(window)
        self._set_ocr_text(self._format_ocr(window, snapshot))
        return snapshot

    def _fill_live_state(self, history_file: object, window: object, ocr_snapshot: OcrSnapshot | None) -> None:
        snapshot = build_live_snapshot(history_file, window, ocr_snapshot)
        self._set_live_text(format_live_snapshot(snapshot))

    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _set_hand_text(self, content: str) -> None:
        self.hand_text.configure(state="normal")
        self.hand_text.delete("1.0", tk.END)
        self.hand_text.insert("1.0", content)
        self.hand_text.configure(state="disabled")

    def _set_ocr_text(self, content: str) -> None:
        self.ocr_text.configure(state="normal")
        self.ocr_text.delete("1.0", tk.END)
        self.ocr_text.insert("1.0", content)
        self.ocr_text.configure(state="disabled")

    def _set_live_text(self, content: str) -> None:
        self.live_text.configure(state="normal")
        self.live_text.delete("1.0", tk.END)
        self.live_text.insert("1.0", content)
        self.live_text.configure(state="disabled")

    def _toggle_auto_refresh(self) -> None:
        if self.auto_refresh_var.get():
            self._schedule_refresh()
        elif self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None

    def _schedule_refresh(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self.auto_refresh_var.get():
            self._after_id = self.root.after(self.refresh_ms, self.refresh)

    def _start_recording_session(self) -> None:
        session_dir = self.session_recorder.start_session()
        self.recording_session_var.set(f"Session de capture: {session_dir}")

    def _record_snapshot(self) -> None:
        snapshot = self.session_recorder.record_snapshot()
        if snapshot is None:
            messagebox.showwarning("Snapshot", "Impossible de capturer un snapshot pour le moment.")
            return
        self.recording_session_var.set(
            f"Snapshot enregistre: {snapshot.timestamp} | session {snapshot.session_id}"
        )

    def _start_auto_recording(self) -> None:
        if self.session_recorder.session_dir is None:
            self._start_recording_session()
        self.is_recording = True
        self.recording_session_var.set(
            f"Recording actif | dossier: {self.session_recorder.session_dir} | intervalle: {self.record_interval_ms // 1000}s"
        )
        self._schedule_auto_recording()

    def _stop_auto_recording(self) -> None:
        self.is_recording = False
        if self._record_after_id is not None:
            self.root.after_cancel(self._record_after_id)
            self._record_after_id = None
        self.recording_session_var.set("Recording arrete.")

    def _schedule_auto_recording(self) -> None:
        if self._record_after_id is not None:
            self.root.after_cancel(self._record_after_id)
            self._record_after_id = None
        if self.is_recording:
            self._record_after_id = self.root.after(self.record_interval_ms, self._auto_record_tick)

    def _auto_record_tick(self) -> None:
        if not self.is_recording:
            return
        snapshot = self.session_recorder.record_snapshot()
        if snapshot is not None:
            self.recording_session_var.set(
                f"Recording actif | dernier snapshot: {snapshot.timestamp} | session {snapshot.session_id}"
            )
        self._schedule_auto_recording()

    def _load_latest_session_review(self) -> None:
        sessions = self.session_recorder.list_sessions()
        if not sessions:
            messagebox.showinfo("Review", "Aucune session disponible.")
            return
        self.review_snapshots = self.session_recorder.list_snapshots(sessions[0])
        self.review_index = 0
        self._render_review_snapshot()

    def _move_review(self, step: int) -> None:
        if not self.review_snapshots:
            return
        self.review_index = max(0, min(len(self.review_snapshots) - 1, self.review_index + step))
        self._render_review_snapshot()

    def _render_review_snapshot(self) -> None:
        if not self.review_snapshots:
            return
        snapshot = self.review_snapshots[self.review_index]

        if self.review_image_label is not None and snapshot.get("image_path"):
            image = Image.open(snapshot["image_path"]).convert("RGB")
            image.thumbnail((900, 620))
            photo = ImageTk.PhotoImage(image)
            self.review_image_label.configure(image=photo, text="")
            self.review_image_label.image = photo
            self.review_image_tk = photo

        if self.review_text is not None:
            payload = snapshot.get("payload", {})
            summary = {
                "index": self.review_index + 1,
                "total": len(self.review_snapshots),
                "timestamp": payload.get("timestamp", ""),
                "window": payload.get("window", {}),
                "history_file": payload.get("history_file", ""),
                "live_snapshot": payload.get("live_snapshot", {}),
            }
            self.review_text.configure(state="normal")
            self.review_text.delete("1.0", tk.END)
            self.review_text.insert("1.0", json.dumps(summary, indent=2, ensure_ascii=False))
            self.review_text.configure(state="disabled")

    def _save_calibration(self) -> None:
        zones: dict[str, list[float]] = {}
        try:
            for name, vars_for_zone in self.calibration_entries.items():
                values = [float(var.get().replace(",", ".")) for var in vars_for_zone]
                if len(values) != 4 or not (0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
                    raise ValueError(name)
                zones[name] = values
        except ValueError as exc:
            messagebox.showerror("Calibration invalide", f"Valeurs invalides pour la zone {exc}.")
            return

        save_calibration({"zones": zones})
        messagebox.showinfo("Calibration", "Calibration enregistree.")
        self._redraw_calibration_preview()

    def _reload_calibration(self) -> None:
        calibration = load_calibration()
        for name, values in calibration.get("zones", {}).items():
            for var, value in zip(self.calibration_entries.get(name, []), values, strict=True):
                var.set(f"{value:.2f}")
        self._redraw_calibration_preview()

    def _reset_calibration_defaults(self) -> None:
        defaults = DEFAULT_CALIBRATION.get("zones", {})
        for name, values in defaults.items():
            for var, value in zip(self.calibration_entries.get(name, []), values, strict=True):
                var.set(f"{value:.2f}")
        self._redraw_calibration_preview()

    def _refresh_calibration_preview(self) -> None:
        detection = summarize_detection()
        window = detection["active_table_window"]
        if window is None:
            windows = list_winamax_windows()
            window = select_preferred_table_window(windows)
        if window is None:
            window = self.last_detected_window
        self._update_calibration_preview(window)

    def _update_calibration_preview(self, window: object) -> None:
        if self.calibration_preview_label is None:
            return
        if window is None:
            image_path = self._find_latest_capture_file()
            if image_path is None:
                self.calibration_preview_label.configure(text="Aucune capture disponible.", image="")
                self.calibration_preview_image = None
                self.last_preview_source_path = None
                return
        else:
            image_path = capture_window(window)
            self.last_detected_window = window
        if not image_path:
            image_path = self._find_latest_capture_file()
            if image_path is None:
                self.calibration_preview_label.configure(text="Capture impossible.", image="")
                self.calibration_preview_image = None
                self.last_preview_source_path = None
                return

        self.last_preview_source_path = image_path
        preview = self._build_calibration_preview_image(image_path)
        photo = ImageTk.PhotoImage(preview)
        self.calibration_preview_label.configure(image=photo, text="")
        self.calibration_preview_label.image = photo
        self.calibration_preview_image = photo

    def _redraw_calibration_preview(self) -> None:
        if self.calibration_preview_label is None:
            return
        image_path = self.last_preview_source_path or self._find_latest_capture_file()
        if not image_path:
            self.calibration_preview_label.configure(text="Aucune capture disponible.", image="")
            self.calibration_preview_image = None
            return

        preview = self._build_calibration_preview_image(image_path)
        photo = ImageTk.PhotoImage(preview)
        self.calibration_preview_label.configure(image=photo, text="")
        self.calibration_preview_label.image = photo
        self.calibration_preview_image = photo

    @staticmethod
    def _find_latest_capture_file() -> str | None:
        capture_dir = Path.home() / "AppData" / "Local" / "Temp" / "winamax_poker_tracker"
        if not capture_dir.exists():
            return None
        candidates = [item for item in capture_dir.glob("table_*.png") if item.stem.count("_") == 2]
        candidates = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)
        return str(candidates[0]) if candidates else None

    def _build_calibration_preview_image(self, image_path: str) -> Image.Image:
        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        width, height = image.size
        palette = [
            "#ff5d5d",
            "#4dd599",
            "#5da9ff",
            "#ffcc5d",
            "#c77dff",
            "#00c2d1",
            "#ff8fab",
            "#90be6d",
            "#f9844a",
            "#43aa8b",
        ]

        zones: dict[str, list[float]] = {}
        for name, vars_for_zone in self.calibration_entries.items():
            try:
                zones[name] = [float(var.get().replace(",", ".")) for var in vars_for_zone]
            except ValueError:
                continue

        for index, (name, values) in enumerate(zones.items()):
            if len(values) != 4:
                continue
            left = int(width * values[0])
            top = int(height * values[1])
            right = int(width * values[2])
            bottom = int(height * values[3])
            color = palette[index % len(palette)]
            draw.rectangle((left, top, right, bottom), outline=color, width=3)
            draw.rectangle((left + 2, top + 2, left + 140, top + 24), fill=(20, 20, 20))
            draw.text((left + 6, top + 5), name, fill=color)

        preview = image.copy()
        preview = ImageEnhance.Brightness(preview).enhance(1.15)
        preview = ImageEnhance.Contrast(preview).enhance(1.15)
        preview.thumbnail((1120, 760))
        return preview

    @staticmethod
    def _format_hand(hand: ParsedHand, source_path: str) -> str:
        lines = [
            f"Source: {source_path}",
            f"Hand ID: {hand.hand_id or '-'}",
            f"Table: {hand.table_name or '-'}",
            f"Format: {hand.table_format or '-'}",
            f"Jeu: {hand.game_type or '-'} | Variante: {hand.variant or '-'}",
            f"Blindes: {hand.small_blind:.2f}/{hand.big_blind:.2f}",
            f"Date: {hand.played_at or '-'}",
            f"Hero: {hand.hero_name or '-'} | Cartes: [{hand.hero_cards or '-'}]",
            "",
            "Joueurs:",
        ]

        if hand.seats:
            for seat in hand.seats:
                lines.append(f"  Seat {seat['seat']}: {seat['player']} ({seat['stack']})")
        else:
            lines.append("  -")

        lines.append("")
        lines.append("Actions:")
        for street, actions in hand.streets.items():
            if street == "meta":
                continue
            lines.append(f"[{street}]")
            if actions:
                for action in actions:
                    lines.append(f"  {action}")
            else:
                lines.append("  -")

        if hand.summary:
            lines.append("")
            lines.append("Summary:")
            for line in hand.summary:
                lines.append(f"  {line}")

        return "\n".join(lines)

    @staticmethod
    def _format_ocr(window: WinamaxWindow, snapshot: OcrSnapshot) -> str:
        lines = [
            f"Fenetre: {window.title}",
            f"PID/HWND: {window.pid}/{window.hwnd}",
            f"Rectangle: {window.rect}",
            f"Capture: {snapshot.image_path or '-'}",
            f"OCR status: {snapshot.status}",
            f"OCR engine: {snapshot.engine_path or 'non detecte'}",
            "",
            "Texte OCR:",
            snapshot.text or "(vide)",
        ]
        if snapshot.zones:
            lines.extend(["", "Zones OCR:"])
            for name, zone in snapshot.zones.items():
                preview = " ".join(line.strip() for line in zone.text.splitlines() if line.strip())[:180]
                lines.append(f"[{name}] {zone.rect}")
                lines.append(f"  {preview or '(vide)'}")
        return "\n".join(lines)

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self._record_after_id is not None:
            self.root.after_cancel(self._record_after_id)
            self._record_after_id = None
        self.root.destroy()


def main() -> None:
    app = PokerTrackerApp()
    app.run()
