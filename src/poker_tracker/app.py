from __future__ import annotations

import json
import hashlib
import random
import ctypes
import re
import tkinter as tk
from dataclasses import is_dataclass, replace
from datetime import datetime
from pathlib import Path
import threading
import time
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageEnhance, ImageOps, ImageTk

from .config import DEFAULT_CALIBRATION, load_calibration, save_calibration
from .detection import (
    HistoryLocation,
    WinamaxProcess,
    WinamaxWindow,
    list_winamax_windows,
    select_preferred_table_window,
    summarize_detection,
)
from .history import latest_hand_block_key, read_history_text
from .live_state import build_fast_live_snapshot, build_live_snapshot, format_live_commentary, format_live_snapshot
from .ocr import OcrSnapshot, capture_window, run_action_ocr_on_image, run_local_ocr, run_local_ocr_on_image, run_local_ocr_on_image_with_profile, run_local_ocr_with_profile
from .parser import ParsedHand, parse_winamax_hand
from .session_recorder import SessionRecorder
from .villain_db import sync_completed_history_file
from .visual import has_active_action_bar


ROOT_DIR = Path(__file__).resolve().parents[2]
REVIEW_FIELDS = [
    "top_left_cards_visible",
    "top_left_name",
    "top_left_stack",
    "top_right_cards_visible",
    "top_right_name",
    "top_right_stack",
    "left_cards_visible",
    "left_name",
    "left_stack",
    "right_cards_visible",
    "right_name",
    "right_stack",
    "hero_name",
    "hero_stack",
    "hero_status",
    "pot_value",
    "dealer_button",
    "board_card_1",
    "board_card_2",
    "board_card_3",
    "board_card_4",
    "board_card_5",
]
REVIEW_CHOICES = ["unknown", "true", "false"]
ELEMENT_REVIEW_CHOICES = ["unknown", "ok", "false", "absent"]
FIELD_LABELS = {
    "top_left_cards_visible": "top_left_cards_visible",
    "top_left_name": "top_left_name",
    "top_left_stack": "top_left_stack",
    "top_right_cards_visible": "top_right_cards_visible",
    "top_right_name": "top_right_name",
    "top_right_stack": "top_right_stack",
    "left_cards_visible": "left_cards_visible",
    "left_name": "left_name",
    "left_stack": "left_stack",
    "right_cards_visible": "right_cards_visible",
    "right_name": "right_name",
    "right_stack": "right_stack",
    "hero_name": "hero_name",
    "hero_stack": "hero_stack",
    "hero_status": "hero_status",
    "pot_value": "pot_value",
    "dealer_button": "dealer_owner",
    "board_card_1": "board_card_1",
    "board_card_2": "board_card_2",
    "board_card_3": "board_card_3",
    "board_card_4": "board_card_4",
    "board_card_5": "board_card_5",
}
CALIBRATION_LABELS = {
    "top_bar": "titre_table",
    "top_left_cards": "top_left_cartes",
    "top_left_name": "top_left_nom",
    "top_left_stack": "top_left_stack",
    "top_right_cards": "top_right_cartes",
    "top_right_name": "top_right_nom",
    "top_right_stack": "top_right_stack",
    "left_cards": "left_cartes",
    "left_name": "left_nom",
    "left_stack": "left_stack",
    "right_cards": "right_cartes",
    "right_name": "right_nom",
    "right_stack": "right_stack",
    "pot": "zone_pot",
    "pot_value": "texte_pot",
    "board": "board_global",
    "board_card_1": "board_carte_1",
    "board_card_2": "board_carte_2",
    "board_card_3": "board_carte_3",
    "board_card_4": "board_carte_4",
    "board_card_5": "board_carte_5",
    "hero": "hero_global",
    "hero_name": "hero_nom",
    "hero_stack": "hero_stack",
    "hero_status": "hero_cartes",
    "dealer_button": "dealer_bouton",
    "actions": "zone_actions",
    "action_left": "bouton_fold_gauche",
    "action_center": "bouton_call_check_centre",
    "action_right": "bouton_raise_bet_droite",
    "left_opponent": "zone_joueur_gauche",
    "right_opponent": "zone_joueur_droite",
}
POSITION_HELP = (
    "Positions utiles: top_left = joueur en haut a gauche, "
    "top_right = joueur en haut a droite, right = joueur a droite, hero = toi en bas. "
    "Pour dealer_owner, mets de preference le nom du joueur ou une de ces positions."
)
FIELD_ZONE_MAP = {
    "top_left_cards_visible": "top_left_cards",
    "top_left_name": "top_left_name",
    "top_left_stack": "top_left_stack",
    "top_right_cards_visible": "top_right_cards",
    "top_right_name": "top_right_name",
    "top_right_stack": "top_right_stack",
    "left_cards_visible": "left_cards",
    "left_name": "left_name",
    "left_stack": "left_stack",
    "right_cards_visible": "right_cards",
    "right_name": "right_name",
    "right_stack": "right_stack",
    "hero_name": "hero_name",
    "hero_stack": "hero_stack",
    "hero_status": "hero_status",
    "pot_value": "pot",
    "dealer_button": "dealer_button",
    "board_card_1": "board_card_1",
    "board_card_2": "board_card_2",
    "board_card_3": "board_card_3",
    "board_card_4": "board_card_4",
    "board_card_5": "board_card_5",
}


class PokerTrackerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Winamax Poker Tracker Prototype")
        self.root.geometry("1680x980")

        self.status_var = tk.StringVar(value="Pret pour le premier scan.")
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.live_debug_var = tk.BooleanVar(value=False)
        self.refresh_ms = 5000
        self.fast_refresh_ms = 200
        self.background_refresh_every = 20
        self._after_id: str | None = None
        self._record_after_id: str | None = None
        self.calibration_entries: dict[str, list[tk.StringVar]] = {}
        self._calibration_redraw_after_id: str | None = None
        self.calibration_preview_label: tk.Label | None = None
        self.calibration_preview_image: ImageTk.PhotoImage | None = None
        self.last_detected_window: WinamaxWindow | None = None
        self.last_preview_source_path: str | None = None
        self.calibration_status_var = tk.StringVar(value="Aucune image de calibration chargée.")
        self.calibration_snapshots: list[dict] = []
        self.calibration_index = 0
        self.session_recorder = SessionRecorder(ROOT_DIR / "sessions")
        self.recording_session_var = tk.StringVar(value="Aucune session de capture.")
        self.record_interval_ms = 5000
        self.is_recording = False
        self.recording_in_progress = False
        self.pending_record_result: tuple[object | None, str] | None = None
        self.review_image_label: tk.Label | None = None
        self.review_image_tk: ImageTk.PhotoImage | None = None
        self.review_text: tk.Text | None = None
        self.review_snapshots: list[dict] = []
        self.review_index = 0
        self.review_status_var = tk.StringVar(value="Aucune annotation sauvegardée.")
        self.review_global_status_var = tk.StringVar(value="review_later")
        self.review_note_var = tk.StringVar(value="")
        self.review_field_vars: dict[str, tk.StringVar] = {field: tk.StringVar(value="unknown") for field in REVIEW_FIELDS}
        self.review_expected_vars: dict[str, tk.StringVar] = {field: tk.StringVar(value="") for field in REVIEW_FIELDS}
        self.review_detected_vars: dict[str, tk.StringVar] = {field: tk.StringVar(value="-") for field in REVIEW_FIELDS}
        self.element_review_field_var = tk.StringVar(value=REVIEW_FIELDS[0])
        self.element_review_status_var = tk.StringVar(value="Aucun echantillon charge.")
        self.element_review_choice_var = tk.StringVar(value="unknown")
        self.element_review_expected_var = tk.StringVar(value="")
        self.element_review_detected_var = tk.StringVar(value="-")
        self.element_review_samples: list[dict] = []
        self.element_review_index = 0
        self.element_review_image_label: tk.Label | None = None
        self.element_review_image_tk: ImageTk.PhotoImage | None = None
        self.last_live_commentary_key: tuple | None = None
        self.last_fast_live_signature: tuple | None = None
        self.live_tick_counter = 0
        self.current_detection: dict[str, object] | None = None
        self.last_full_ocr_key: tuple[str, str, bool] | None = None
        self.last_full_ocr_at = 0.0
        self.live_decision_text: tk.Text | None = None
        self.last_live_scan_at = ""
        self.last_live_capture_path = ""
        self.last_live_window: WinamaxWindow | None = None
        self.decision_overlay: tk.Toplevel | None = None
        self.decision_overlay_label: tk.Label | None = None
        self.player_range_overlays: dict[str, tuple[tk.Toplevel, tk.Label]] = {}
        self.live_action_memory: list[str] = []
        self.live_action_memory_hand = ""
        self.live_action_memory_seen: set[str] = set()
        self.cached_live_context: dict[str, object] = {}
        self.cached_history_block_key = ""
        self.cached_board_signature = ""
        self.cached_board_card_fingerprints: dict[str, bytes] = {}
        self.pending_board_cards: dict[str, tuple[str, int]] = {}
        self.cached_hero_signature = ""
        self.full_ocr_thread: threading.Thread | None = None
        self.full_ocr_in_progress = False
        self.pending_full_ocr_result: tuple[int, object, object, OcrSnapshot | None, object | None, float, str, dict[str, bytes]] | None = None
        self.pending_full_ocr_request: tuple[int, object, object, str] | None = None
        self.latest_full_ocr_request_id = 0
        self.latest_applied_full_ocr_id = 0
        self.pending_turn_snapshot: object | None = None
        self.current_live_snapshot: object | None = None
        self.full_ocr_display_until = 0.0
        self.hero_turn_release_streak = 0
        self.pending_hand_change = False
        self.last_history_import_summary = ""

        self._build_layout()

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

        ttk.Button(header, text="Snapshot live", command=self._capture_live_snapshot_once).grid(
            row=0, column=5, rowspan=2, padx=(12, 0)
        )
        self.live_debug_button = ttk.Button(header, text="Lancer live debug", command=self._toggle_live_debug)
        self.live_debug_button.grid(row=0, column=6, rowspan=2, padx=(12, 0))

        start_record_button = ttk.Button(header, text="Start recording", command=self._start_auto_recording)
        start_record_button.grid(row=0, column=7, rowspan=2, padx=(12, 0))

        stop_record_button = ttk.Button(header, text="Stop recording", command=self._stop_auto_recording)
        stop_record_button.grid(row=0, column=8, rowspan=2, padx=(12, 0))

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.live_decision_text = self._create_text_tab(notebook, "Assistant live")

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
            text="Zones relatives de la table Winamax (left, top, width, height).",
        ).grid(row=0, column=0, sticky="w")

        controls_container = ttk.Frame(frame)
        controls_container.grid(row=1, column=0, sticky="nsw", pady=(10, 10))
        controls_container.columnconfigure(0, weight=1)
        controls_container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(controls_container, width=470, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsw")
        scrollbar = ttk.Scrollbar(controls_container, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        grid = ttk.Frame(canvas)
        grid_window = canvas.create_window((0, 0), window=grid, anchor="nw")

        def sync_calibration_scroll_region(_event: object) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def sync_calibration_width(_event: object) -> None:
            canvas.itemconfigure(grid_window, width=_event.width)

        grid.bind("<Configure>", sync_calibration_scroll_region)
        canvas.bind("<Configure>", sync_calibration_width)

        def _on_calibration_mousewheel(event: tk.Event[tk.Misc]) -> None:
            delta = -1 * int(event.delta / 120) if event.delta else 0
            if delta:
                canvas.yview_scroll(delta, "units")

        canvas.bind_all("<MouseWheel>", _on_calibration_mousewheel)

        calibration = load_calibration()
        zones = calibration.get("zones", {})
        headers = ("Zone", "Left", "Top", "Width", "Height")
        for col, header in enumerate(headers):
            ttk.Label(grid, text=header).grid(row=0, column=col, padx=4, pady=2, sticky="w")

        for row, (name, values) in enumerate(zones.items(), start=1):
            ttk.Label(grid, text=CALIBRATION_LABELS.get(name, name)).grid(row=row, column=0, padx=4, pady=2, sticky="w")
            vars_for_zone: list[tk.StringVar] = []
            left, top, right, bottom = values
            display_values = [left, top, max(0.0, right - left), max(0.0, bottom - top)]
            for col, value in enumerate(display_values, start=1):
                var = tk.StringVar(value=f"{value:.2f}")
                spin = ttk.Spinbox(
                    grid,
                    textvariable=var,
                    from_=0.0,
                    to=1.0,
                    increment=0.01,
                    width=8,
                    command=self._schedule_calibration_redraw,
                )
                spin.grid(row=row, column=col, padx=4, pady=2, sticky="w")
                spin.bind("<KeyRelease>", lambda _event: self._schedule_calibration_redraw())
                spin.bind("<<Increment>>", lambda _event: self._schedule_calibration_redraw())
                spin.bind("<<Decrement>>", lambda _event: self._schedule_calibration_redraw())
                var.trace_add("write", self._on_calibration_var_changed)
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
        ttk.Button(buttons, text="Charger dernière session", command=self._load_latest_calibration_session).grid(
            row=0, column=5, padx=(8, 0)
        )
        ttk.Button(buttons, text="Image précédente", command=lambda: self._move_calibration_image(-1)).grid(
            row=0, column=6, padx=(8, 0)
        )
        ttk.Button(buttons, text="Image suivante", command=lambda: self._move_calibration_image(1)).grid(
            row=0, column=7, padx=(8, 0)
        )
        ttk.Label(buttons, textvariable=self.calibration_status_var).grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))

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
        self.calibration_preview_label.bind("<Configure>", lambda _event: self._redraw_calibration_preview())

    def _create_review_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        frame.columnconfigure(0, weight=3)
        frame.columnconfigure(1, weight=2)
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
        ttk.Label(controls, text="Statut global").grid(row=0, column=3, padx=(12, 6))
        ttk.Combobox(
            controls,
            textvariable=self.review_global_status_var,
            values=["review_later", "correct", "incorrect"],
            width=14,
            state="readonly",
        ).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(controls, text="Valider les annotations", command=self._save_review_annotation).grid(
            row=0, column=5, padx=(0, 8)
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

        self.review_text = tk.Text(frame, wrap="word", font=("Consolas", 10), width=48)
        self.review_text.grid(row=1, column=1, sticky="nsew")
        self.review_text.configure(state="disabled")

        review_footer = ttk.Frame(frame)
        review_footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        review_footer.columnconfigure(2, weight=1)
        ttk.Label(review_footer, textvariable=self.review_status_var).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(review_footer, text="Note:").grid(row=0, column=1, sticky="w")
        ttk.Entry(review_footer, textvariable=self.review_note_var, width=60).grid(row=0, column=2, sticky="ew", padx=(8, 0))
        ttk.Label(review_footer, text=POSITION_HELP, wraplength=1200, foreground="#555555").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        fields_frame = ttk.LabelFrame(frame, text="Validation par element", padding=8)
        fields_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        for base_col in (0, 4, 8):
            ttk.Label(fields_frame, text="Champ").grid(row=0, column=base_col, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(fields_frame, text="Détecté").grid(row=0, column=base_col + 1, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(fields_frame, text="Etat").grid(row=0, column=base_col + 2, sticky="w", padx=(0, 6), pady=4)
            ttk.Label(fields_frame, text="Valeur attendue").grid(
                row=0, column=base_col + 3, sticky="w", padx=(0, 12), pady=4
            )
        for idx, field in enumerate(REVIEW_FIELDS):
            group = idx // 6
            local_row = (idx % 6) + 1
            base_col = group * 4
            ttk.Label(fields_frame, text=FIELD_LABELS.get(field, field)).grid(
                row=local_row, column=base_col, sticky="w", padx=(0, 6), pady=4
            )
            ttk.Label(fields_frame, textvariable=self.review_detected_vars[field], width=16).grid(
                row=local_row, column=base_col + 1, sticky="w", padx=(0, 10), pady=4
            )
            combo = ttk.Combobox(
                fields_frame,
                textvariable=self.review_field_vars[field],
                values=REVIEW_CHOICES,
                width=10,
                state="readonly",
            )
            combo.grid(row=local_row, column=base_col + 2, sticky="w", padx=(0, 10), pady=4)
            ttk.Entry(fields_frame, textvariable=self.review_expected_vars[field], width=24).grid(
                row=local_row, column=base_col + 3, sticky="ew", padx=(0, 16), pady=4
            )

    def _create_element_review_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        frame.columnconfigure(0, weight=3)
        frame.columnconfigure(1, weight=2)
        frame.rowconfigure(1, weight=1)
        notebook.add(frame, text="Review element")

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(controls, text="Element").grid(row=0, column=0, padx=(0, 6))
        ttk.Combobox(
            controls,
            textvariable=self.element_review_field_var,
            values=REVIEW_FIELDS,
            width=24,
            state="readonly",
        ).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(controls, text="Charger derniere session", command=self._load_element_review_samples).grid(
            row=0, column=2, padx=(0, 8)
        )
        ttk.Button(controls, text="Nouveau tirage", command=self._shuffle_element_review_samples).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Button(controls, text="Precedent", command=lambda: self._move_element_review(-1)).grid(
            row=0, column=4, padx=(0, 8)
        )
        ttk.Button(controls, text="Suivant", command=lambda: self._move_element_review(1)).grid(
            row=0, column=5, padx=(0, 8)
        )

        self.element_review_image_label = tk.Label(
            frame,
            text="Aucun echantillon charge.",
            anchor="center",
            bg="#1f1f1f",
            fg="#f2f2f2",
            relief="sunken",
            bd=1,
        )
        self.element_review_image_label.grid(row=1, column=0, sticky="nsew", padx=(0, 12))

        side = ttk.Frame(frame)
        side.grid(row=1, column=1, sticky="nsew")
        side.columnconfigure(1, weight=1)

        ttk.Label(side, textvariable=self.element_review_status_var, wraplength=420).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        ttk.Label(side, text="Detecte").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(side, textvariable=self.element_review_detected_var, wraplength=320).grid(
            row=1, column=1, sticky="w", pady=4
        )
        ttk.Label(side, text="Verdict").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(
            side,
            textvariable=self.element_review_choice_var,
            values=ELEMENT_REVIEW_CHOICES,
            width=18,
            state="readonly",
        ).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(side, text="Valeur attendue").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(side, textvariable=self.element_review_expected_var, width=32).grid(
            row=3, column=1, sticky="ew", pady=4
        )
        ttk.Button(side, text="Valider element", command=self._save_element_review_annotation).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        ttk.Label(
            side,
            text="Review rapide par element: on te montre des crops aleatoires d'une meme zone.",
            wraplength=420,
            foreground="#555555",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def refresh(self) -> None:
        detection = summarize_detection()
        self._apply_detection(detection)
        ocr_snapshot = self._fill_ocr(detection["active_table_window"])
        self._fill_live_state(detection["latest_history_file"], detection["active_table_window"], ocr_snapshot)
        self._schedule_refresh()

    def _apply_detection(self, detection: dict[str, object]) -> None:
        self.current_detection = detection
        self.last_detected_window = detection["active_table_window"]
        process_count = len(detection["processes"])
        window_count = len(detection["windows"])
        history_count = len(detection["history_locations"])
        self.status_var.set(
            f"Scan termine: {process_count} processus, {window_count} fenetres, {history_count} emplacements historiques."
        )

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
        if not hasattr(self, "hand_text") or self.hand_text is None:
            return
        if history_file is None:
            self._set_hand_text("Aucun fichier d'historique detecte.")
            return

        raw_text = read_history_text(history_file.path)
        parsed = parse_winamax_hand(raw_text)
        self._set_hand_text(self._format_hand(parsed, history_file.path))

    def _fill_ocr(self, window: object) -> OcrSnapshot | None:
        if not hasattr(self, "ocr_text") or self.ocr_text is None:
            if window is None:
                return None
            self.last_live_scan_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            return run_local_ocr_with_profile(window, profile="live")
        if window is None:
            self._set_ocr_text("Aucune fenetre de table Winamax active detectee.")
            return None

        self.last_live_scan_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        snapshot = run_local_ocr_with_profile(window, profile="live")
        self.last_live_capture_path = snapshot.image_path or self.last_live_capture_path
        self._set_ocr_text(self._format_ocr(window, snapshot))
        return snapshot

    def _fill_live_state(self, history_file: object, window: object, ocr_snapshot: OcrSnapshot | None) -> None:
        if isinstance(window, WinamaxWindow):
            self.last_live_window = window
        block_key = latest_hand_block_key(history_file)
        board_signature = self._board_signature(ocr_snapshot.image_path if ocr_snapshot else "")
        hero_signature = self._hero_signature(ocr_snapshot.image_path if ocr_snapshot else "")
        same_hand = self._same_live_hand(block_key, hero_signature)
        reuse_hero = (
            same_hand
            and bool(self.cached_hero_signature)
            and hero_signature == self.cached_hero_signature
        )
        reuse_board = same_hand and board_signature and board_signature == self.cached_board_signature
        cached_names = {
            field: str(self.cached_live_context.get(field, "") or "")
            for field in ("top_left_name", "top_right_name", "left_name", "right_name", "hero_name")
        }
        snapshot = build_live_snapshot(
            history_file,
            window,
            ocr_snapshot,
            hero_name_hint=str(self.cached_live_context.get("hero_name", "") or "RougeLion"),
            hero_cards_hint=(str(self.cached_live_context.get("hero_cards", "") or "") if reuse_hero else ""),
            visible_board_hint=(str(self.cached_live_context.get("visible_board", "") or "") if reuse_board else ""),
            cached_names=cached_names if same_hand else None,
        )
        snapshot = self._stabilize_board_cards(
            snapshot,
            self._board_card_fingerprints(ocr_snapshot.image_path if ocr_snapshot else ""),
            same_hand,
        )
        self.current_live_snapshot = self._preserve_live_details(
            self.current_live_snapshot,
            snapshot,
            same_hand=same_hand,
        )
        snapshot = self.current_live_snapshot
        self._update_cached_live_context(snapshot)
        self.cached_board_card_fingerprints = self._board_card_fingerprints(ocr_snapshot.image_path if ocr_snapshot else "")
        self._render_live_decision(snapshot, full_ocr=True)

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
        if not hasattr(self, "ocr_text") or self.ocr_text is None:
            return
        self.ocr_text.configure(state="normal")
        self.ocr_text.delete("1.0", tk.END)
        self.ocr_text.insert("1.0", content)
        self.ocr_text.configure(state="disabled")

    def _set_live_text(self, content: str) -> None:
        if not hasattr(self, "live_text") or self.live_text is None:
            return
        self.live_text.configure(state="normal")
        self.live_text.delete("1.0", tk.END)
        self.live_text.insert("1.0", content)
        self.live_text.configure(state="disabled")

    def _set_live_commentary_text(self, content: str) -> None:
        if not hasattr(self, "live_commentary_text") or self.live_commentary_text is None:
            return
        self.live_commentary_text.configure(state="normal")
        self.live_commentary_text.delete("1.0", tk.END)
        self.live_commentary_text.insert("1.0", content)
        self.live_commentary_text.configure(state="disabled")

    def _append_live_commentary(self, snapshot: object) -> None:
        if not hasattr(self, "live_commentary_text") or self.live_commentary_text is None:
            return
        if snapshot is None:
            self._set_live_commentary_text("Aucune table live exploitable pour le moment.")
            self.last_live_commentary_key = None
            return

        commentary_key = (
            getattr(snapshot, "hand_id", ""),
            getattr(snapshot, "current_street", ""),
            getattr(snapshot, "visible_board", ""),
            getattr(snapshot, "pot_text", ""),
            getattr(snapshot, "is_hero_turn", False),
            tuple(getattr(snapshot, "available_actions", []) or []),
            tuple(getattr(snapshot, "recent_actions", [])[-3:] or []),
        )
        if commentary_key == self.last_live_commentary_key:
            return

        self.last_live_commentary_key = commentary_key
        timestamp = datetime.now().strftime("%H:%M:%S")
        content = format_live_commentary(snapshot)
        block = f"=== {timestamp} ===\n{content}\n\n"

        self.live_commentary_text.configure(state="normal")
        existing = self.live_commentary_text.get("1.0", tk.END).strip()
        if not existing or existing == "Aucune table live exploitable pour le moment.":
            self.live_commentary_text.delete("1.0", tk.END)
            self.live_commentary_text.insert("1.0", block)
        else:
            self.live_commentary_text.insert("end", block)
        self.live_commentary_text.see("end")
        self.live_commentary_text.configure(state="disabled")

    def _toggle_auto_refresh(self) -> None:
        if self.auto_refresh_var.get():
            self._schedule_refresh()
        elif self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None

    def _toggle_live_debug(self) -> None:
        self.live_debug_var.set(not self.live_debug_var.get())
        if self.live_debug_var.get():
            session_dir = self.session_recorder.ensure_session()
            self.auto_refresh_var.set(True)
            self.live_debug_button.configure(text="Arreter live debug")
            self.recording_session_var.set(f"Audit live automatique : {session_dir}")
            self.status_var.set("Live debug actif : chaque tour hero complet sera archive.")
            self._schedule_refresh()
        else:
            self.auto_refresh_var.set(False)
            self.live_debug_button.configure(text="Lancer live debug")
            self.status_var.set("Live debug arrete.")

    def _capture_live_snapshot_once(self) -> None:
        detection = summarize_detection()
        self._apply_detection(detection)
        window = detection.get("active_table_window")
        if window is None:
            self.status_var.set("Snapshot live impossible : aucune table Winamax detectee.")
            return
        image_path = capture_window(window)
        if not image_path:
            self.status_var.set("Snapshot live impossible : capture de fenetre echouee.")
            return
        self.last_live_capture_path = image_path
        self.last_live_scan_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        ocr_snapshot = run_local_ocr_on_image_with_profile(image_path, profile="live")
        self._set_ocr_text(self._format_ocr(window, ocr_snapshot))
        self._fill_live_state(detection.get("latest_history_file"), window, ocr_snapshot)
        self.status_var.set(f"Snapshot live termine : {image_path}")
    def _schedule_refresh(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self.auto_refresh_var.get():
            self._after_id = self.root.after(self.fast_refresh_ms, self._live_tick)

    def _live_tick(self) -> None:
        self._after_id = None
        self._consume_pending_full_ocr()

        if time.monotonic() < self.full_ocr_display_until and self.current_live_snapshot is not None:
            self._render_live_decision(self.current_live_snapshot, full_ocr=True, preserve_details=True)
            self.status_var.set("Snapshot detaille courant affiche.")
            self._schedule_refresh()
            return

        if self.full_ocr_in_progress:
            self.status_var.set("Tour detecte: snapshot fige, analyse detaillee en cours...")
            self._schedule_refresh()
            return

        self.live_tick_counter += 1

        needs_detection = self.current_detection is None
        if not needs_detection and self.live_tick_counter % self.background_refresh_every == 0:
            needs_detection = True

        if needs_detection:
            detection = summarize_detection()
            self._apply_detection(detection)
        else:
            detection = self.current_detection or summarize_detection()

        history_file = detection.get("latest_history_file")
        window = detection.get("active_table_window")
        if isinstance(window, WinamaxWindow):
            self.last_live_window = window
        self._sync_completed_history(history_file)
        history_block_key = latest_hand_block_key(history_file)
        if (
            self.current_live_snapshot is not None
            and self.cached_history_block_key
            and history_block_key
            and history_block_key != self.cached_history_block_key
        ):
            # Do not blank the debug panel just because the hand-history file
            # advanced. Keep the last verified state until the hero turn gives
            # us a complete, fresh read of the new hand.
            self.pending_hand_change = True
            self.full_ocr_display_until = 0.0
        if window is None:
            self.current_live_snapshot = None
            self.full_ocr_display_until = 0.0
            self._render_live_decision(None, full_ocr=False)
            self.status_var.set("Scan rapide actif, mais aucune table Winamax visible.")
            self._schedule_refresh()
            return

        image_path = capture_window(window)
        self.last_live_scan_at = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.last_live_capture_path = image_path or ""
        action_texts = run_action_ocr_on_image(image_path) if image_path and has_active_action_bar(image_path) else {}
        fast_snapshot = build_fast_live_snapshot(
            history_file,
            window,
            image_path,
            action_texts,
            self.cached_live_context,
        )
        # The action buttons can stay identical (FOLD/CHECK/RAISE) when a
        # street changes. Include the card glyphs so a hero who acts first on
        # the flop/turn/river still receives a fresh decision.
        fast_signature = self._fast_live_signature(
            fast_snapshot,
            board_signature=self._board_signature(image_path or ""),
            hero_signature=self._hero_signature(image_path or ""),
        )

        if (
            self.current_live_snapshot is not None
            and getattr(self.current_live_snapshot, "is_hero_turn", False)
            and fast_snapshot is not None
            and getattr(fast_snapshot, "is_hero_turn", False)
            and fast_signature == self.last_fast_live_signature
        ):
            self.hero_turn_release_streak = 0
            self._render_live_decision(self.current_live_snapshot, full_ocr=True, preserve_details=True)
            self.status_var.set("Ton tour est toujours detecte. Snapshot detaille conserve.")
            self._schedule_refresh()
            return

        self.last_fast_live_signature = fast_signature

        if self.current_live_snapshot is not None and getattr(self.current_live_snapshot, "is_hero_turn", False):
            if fast_snapshot is None or not getattr(fast_snapshot, "is_hero_turn", False):
                self.hero_turn_release_streak += 1
            else:
                self.hero_turn_release_streak = 0
            if self.hero_turn_release_streak < 2:
                self._render_live_decision(self.current_live_snapshot, full_ocr=True, preserve_details=True)
                self.status_var.set("Verification de fin de tour en cours. Snapshot detaille conserve.")
                self._schedule_refresh()
                return
            self.current_live_snapshot = self._merge_fast_turn_state(
                self.current_live_snapshot,
                fast_snapshot,
            )
            self.hero_turn_release_streak = 0

        should_run_full_ocr = self._should_run_full_ocr(fast_snapshot)
        if should_run_full_ocr:
            self.hero_turn_release_streak = 0
            self._queue_full_ocr_request(history_file, window, image_path or "")
            self.pending_turn_snapshot = fast_snapshot
            self._render_live_decision(fast_snapshot, full_ocr=False, analysis_pending=True)
            self.status_var.set("Tour detecte: analyse complete en cours...")
        else:
            self.pending_turn_snapshot = None
            self.full_ocr_display_until = 0.0
            if self.current_live_snapshot is not None:
                self._render_live_decision(self.current_live_snapshot, full_ocr=True, preserve_details=True)
                self.status_var.set("Scan rapide en boucle. Dernier snapshot detaille conserve.")
            else:
                self._render_live_decision(fast_snapshot, full_ocr=False, analysis_pending=False)
                self.status_var.set(
                    f"Scan rapide en boucle ({self.fast_refresh_ms} ms). "
                    f"Confiance tour: {getattr(fast_snapshot, 'hero_turn_confidence', 0.0):.2f}"
                )

        self._schedule_refresh()

    def _sync_completed_history(self, history_file: object | None) -> None:
        """Persist newly completed hands before their ranges are reused live.

        The history file is polled often, but ``sync_completed_history_file``
        only opens/imports when its size changed and ignores known hand IDs.
        In-progress hands are deliberately excluded: recording them early would
        turn partial action lines into incorrect VPIP/PFR/call statistics.
        """
        history_path = str(getattr(history_file, "path", "") or "")
        if not history_path:
            return
        try:
            stats = sync_completed_history_file(history_path)
        except (OSError, ValueError):
            # A Winamax file can be momentarily unavailable while it is being
            # written. The next short live tick will retry safely.
            return
        if stats.hands_inserted:
            self.last_history_import_summary = (
                f"BDD live : +{stats.hands_inserted} main(s), "
                f"+{stats.actions_inserted} action(s)"
            )

    def _should_run_full_ocr(self, snapshot: object) -> bool:
        if snapshot is None:
            return False
        if getattr(snapshot, "is_hero_turn", False):
            return True
        return False

    @staticmethod
    def _merge_fast_turn_state(detailed_snapshot: object, fast_snapshot: object | None) -> object:
        """Keep hand details while refreshing only the cheap turn indicators."""
        if fast_snapshot is None or not is_dataclass(detailed_snapshot):
            return detailed_snapshot
        fast_players = list(getattr(fast_snapshot, "players_in_hand", []) or [])
        return replace(
            detailed_snapshot,
            is_hero_turn=bool(getattr(fast_snapshot, "is_hero_turn", False)),
            hero_turn_confidence=float(getattr(fast_snapshot, "hero_turn_confidence", 0.0) or 0.0),
            available_actions=list(getattr(fast_snapshot, "available_actions", []) or []),
            visual_buttons=list(getattr(fast_snapshot, "visual_buttons", []) or []),
            players_in_hand=fast_players,
            ocr_status="cached_between_turns",
        )

    @staticmethod
    def _fast_live_signature(
        snapshot: object,
        *,
        board_signature: str = "",
        hero_signature: str = "",
    ) -> tuple | None:
        """Stable cheap state key used before deciding to keep old details."""
        if snapshot is None:
            return None
        return (
            bool(getattr(snapshot, "is_hero_turn", False)),
            tuple(getattr(snapshot, "available_actions", []) or []),
            tuple(getattr(snapshot, "visual_buttons", []) or []),
            board_signature,
            hero_signature,
        )

    def _queue_full_ocr_request(self, history_file: object, window: object, image_path: str) -> None:
        if not image_path:
            return
        request_id = self.live_tick_counter
        self.latest_full_ocr_request_id = request_id
        frozen_path = self._freeze_live_capture(image_path)
        self.pending_full_ocr_request = (request_id, history_file, window, frozen_path or image_path)
        if not self.full_ocr_in_progress:
            self._start_next_full_ocr_job()

    def _start_next_full_ocr_job(self) -> None:
        if self.full_ocr_in_progress or self.pending_full_ocr_request is None:
            return
        request_id, history_file, window, image_path = self.pending_full_ocr_request
        self.pending_full_ocr_request = None
        self.full_ocr_in_progress = True

        def worker() -> None:
            try:
                local_actions = list(self.live_action_memory)
                analysis_started = time.perf_counter()
                block_key = latest_hand_block_key(history_file)
                board_signature = self._board_signature(image_path)
                hero_signature = self._hero_signature(image_path)
                same_hand = self._same_live_hand(block_key, hero_signature)
                reuse_hero = (
                    same_hand
                    and bool(self.cached_live_context.get("hero_cards"))
                    and bool(self.cached_hero_signature)
                    and hero_signature == self.cached_hero_signature
                )
                reuse_board = same_hand and bool(self.cached_board_signature) and board_signature == self.cached_board_signature
                have_names = same_hand and any(self.cached_live_context.get(field) for field in ("top_left_name", "top_right_name", "left_name", "right_name"))
                profile = ("live_without_hero_board_and_names" if reuse_hero and reuse_board and have_names else
                           "live_without_hero_and_board" if reuse_hero and reuse_board else
                           "live_without_hero_cards" if reuse_hero else "live")
                snapshot = run_local_ocr_on_image_with_profile(image_path, profile=profile) if image_path else None
                cached_names = {
                    field: str(self.cached_live_context.get(field, "") or "")
                    for field in ("top_left_name", "top_right_name", "left_name", "right_name", "hero_name")
                }
                live_snapshot = build_live_snapshot(
                    history_file,
                    window,
                    snapshot,
                    hero_name_hint=str(self.cached_live_context.get("hero_name", "") or "RougeLion"),
                    hero_cards_hint=(str(self.cached_live_context.get("hero_cards", "") or "") if reuse_hero else ""),
                    visible_board_hint=(str(self.cached_live_context.get("visible_board", "") or "") if reuse_board else ""),
                    cached_names=cached_names if same_hand else None,
                    local_recent_actions=local_actions,
                ) if snapshot is not None else None
                elapsed_seconds = time.perf_counter() - analysis_started
                self.pending_full_ocr_result = (
                    request_id,
                    history_file,
                    window,
                    snapshot,
                    live_snapshot,
                    elapsed_seconds,
                    profile,
                    self._board_card_fingerprints(image_path),
                )
            finally:
                self.full_ocr_in_progress = False

        self.full_ocr_thread = threading.Thread(target=worker, daemon=True)
        self.full_ocr_thread.start()

    def _consume_pending_full_ocr(self) -> None:
        if self.pending_full_ocr_result is None:
            return
        request_id, history_file, window, ocr_snapshot, live_snapshot, elapsed_seconds, ocr_profile, board_fingerprints = self.pending_full_ocr_result
        self.pending_full_ocr_result = None
        if request_id < self.latest_full_ocr_request_id:
            self._start_next_full_ocr_job()
            return
        if ocr_snapshot is not None:
            self.last_live_capture_path = ocr_snapshot.image_path or self.last_live_capture_path
            if live_snapshot is not None:
                same_hand = self._same_live_hand(
                    latest_hand_block_key(history_file),
                    self._hero_signature(ocr_snapshot.image_path),
                )
                live_snapshot = self._stabilize_board_cards(live_snapshot, board_fingerprints, same_hand)
                self.current_live_snapshot = self._preserve_live_details(
                    self.current_live_snapshot,
                    live_snapshot,
                    same_hand=same_hand,
                )
                self._remember_live_actions(self.current_live_snapshot)
                self._update_cached_live_context(self.current_live_snapshot)
                self._render_live_decision(self.current_live_snapshot, full_ocr=True)
                audit_record = self.session_recorder.record_live_analysis(
                    image_path=ocr_snapshot.image_path,
                    history_file=history_file,
                    window=window,
                    ocr_snapshot=ocr_snapshot,
                    live_snapshot=self.current_live_snapshot,
                    elapsed_seconds=elapsed_seconds,
                    ocr_profile=ocr_profile,
                )
                if audit_record is not None:
                    self.recording_session_var.set(
                        f"Audit live sauvegarde : {audit_record.metadata_path} | {elapsed_seconds:.2f}s"
                    )
                self.pending_hand_change = False
            else:
                self._fill_live_state(history_file, window, ocr_snapshot)
            self.cached_history_block_key = latest_hand_block_key(history_file)
            self.cached_board_signature = self._board_signature(ocr_snapshot.image_path)
            self.cached_board_card_fingerprints = board_fingerprints
            self.cached_hero_signature = self._hero_signature(ocr_snapshot.image_path)
            self.last_full_ocr_at = time.monotonic()
            # Resume the fast action scan almost immediately. Keeping the
            # detailed frame frozen longer can display CHECK after CALL has
            # appeared on the table.
            self.full_ocr_display_until = self.last_full_ocr_at + 0.2
            self.latest_applied_full_ocr_id = request_id
            self.pending_turn_snapshot = None
            self.hero_turn_release_streak = 0
        self._start_next_full_ocr_job()

    def _remember_live_actions(self, snapshot: object) -> None:
        """Record visible villain bets by street before Winamax writes history."""
        if snapshot is None:
            return
        hero_cards = str(getattr(snapshot, "hero_cards", "") or "")
        if hero_cards and hero_cards != self.live_action_memory_hand:
            self.live_action_memory_hand = hero_cards
            self.live_action_memory = []
            self.live_action_memory_seen = set()
        street = str(getattr(snapshot, "current_street", "preflop") or "preflop")
        fields = getattr(snapshot, "detected_fields", {}) or {}
        for seat in ("top_left", "top_right", "left", "right"):
            raw = str(fields.get(f"{seat}_bet", "") or "")
            match = re.search(r"(\d+(?:[.,]\d+)?)", raw)
            if not match:
                continue
            amount = float(match.group(1).replace(",", "."))
            # Blinds are not aggressive preflop actions.
            if street == "preflop" and amount <= 1.0:
                continue
            name = str(fields.get(f"{seat}_name", "") or seat)
            key = f"{street}|{seat}|{amount:.2f}"
            if key in self.live_action_memory_seen:
                continue
            self.live_action_memory_seen.add(key)
            self.live_action_memory.append(f"{name} bets {amount:g} BB")

    def _update_cached_live_context(self, snapshot: object) -> None:
        if snapshot is None:
            return
        hero_name = self._safe_live_hero_name(getattr(snapshot, "hero_name", ""))
        self.cached_live_context = {
            "table_name": getattr(snapshot, "table_name", ""),
            "hero_name": hero_name,
            "hero_cards": getattr(snapshot, "hero_cards", "") or "",
            "current_street": getattr(snapshot, "current_street", ""),
            "visible_board": getattr(snapshot, "visible_board", ""),
            "top_left_name": (getattr(snapshot, "detected_fields", {}) or {}).get("top_left_name", ""),
            "top_right_name": (getattr(snapshot, "detected_fields", {}) or {}).get("top_right_name", ""),
            "left_name": (getattr(snapshot, "detected_fields", {}) or {}).get("left_name", ""),
            "right_name": (getattr(snapshot, "detected_fields", {}) or {}).get("right_name", ""),
        }

    def _same_live_hand(self, history_block_key: str, hero_signature: str) -> bool:
        """History is delayed; a changed hole-card image always starts a hand."""
        if not self.cached_history_block_key or history_block_key != self.cached_history_block_key:
            return False
        if self.cached_hero_signature and hero_signature and hero_signature != self.cached_hero_signature:
            return False
        return True

    @staticmethod
    def _board_card_fingerprints(image_path: str) -> dict[str, bytes]:
        """Small binary glyph masks, tolerant to harmless screen antialiasing."""
        if not image_path:
            return {}
        try:
            image = Image.open(image_path).convert("L")
            zones = load_calibration().get("zones", {})
            fingerprints: dict[str, bytes] = {}
            for index in range(1, 6):
                ratios = zones.get(f"board_card_{index}_value")
                if not ratios:
                    continue
                rect = tuple(
                    int(value * (image.width if axis % 2 == 0 else image.height))
                    for axis, value in enumerate(ratios)
                )
                crop = ImageOps.autocontrast(image.crop(rect)).resize((24, 32))
                fingerprints[f"board_card_{index}"] = bytes(
                    1 if value < 155 else 0 for value in crop.getdata()
                )
            return fingerprints
        except (OSError, ValueError):
            return {}

    def _stabilize_board_cards(
        self,
        snapshot: object | None,
        fingerprints: dict[str, bytes],
        same_hand: bool,
    ) -> object | None:
        """Do not let OCR rename an already visible board card mid-street."""
        if snapshot is None or not is_dataclass(snapshot):
            return snapshot
        if not same_hand:
            self.pending_board_cards = {}
            return snapshot
        if not hasattr(self, "pending_board_cards"):
            self.pending_board_cards = {}
        fields = dict(getattr(snapshot, "detected_fields", {}) or {})
        previous = getattr(self.current_live_snapshot, "detected_fields", {}) or {}
        changed = False
        for index in range(1, 6):
            key = f"board_card_{index}"
            old_value = str(previous.get(key, "") or "")
            new_value = str(fields.get(key, "") or "")
            # A newly dealt community card must be seen twice with the same
            # rank/suit before it enters the decision engine.  It prevents a
            # single OCR glitch (notably 9/Q and 7/J) from changing equity.
            if not old_value and new_value:
                candidate, count = self.pending_board_cards.get(key, ("", 0))
                count = count + 1 if candidate == new_value else 1
                self.pending_board_cards[key] = (new_value, count)
                if count < 2:
                    fields[key] = ""
                    changed = True
                    continue
                self.pending_board_cards.pop(key, None)
            elif old_value:
                self.pending_board_cards.pop(key, None)
            old_mask = self.cached_board_card_fingerprints.get(key, b"")
            new_mask = fingerprints.get(key, b"")
            if not old_value or not new_mask or len(old_mask) != len(new_mask):
                continue
            similarity = sum(left == right for left, right in zip(old_mask, new_mask)) / len(old_mask)
            if similarity >= 0.90 and new_value != old_value:
                fields[key] = old_value
                changed = True
        if not changed:
            return snapshot
        board = " ".join(
            str(fields.get(f"board_card_{index}", "") or "")
            for index in range(1, 6)
            if fields.get(f"board_card_{index}", "")
        )
        count = len(board.split())
        street = "river" if count >= 5 else "turn" if count == 4 else "flop" if count >= 3 else "preflop"
        return replace(snapshot, detected_fields=fields, visible_board=board, current_street=street)

    @staticmethod
    def _preserve_live_details(previous: object | None, current: object | None, *, same_hand: bool) -> object | None:
        """Do not erase trustworthy hand details when one OCR frame is weak."""
        if previous is None or current is None or not same_hand:
            return current
        if not is_dataclass(previous) or not is_dataclass(current):
            return current

        previous_fields = dict(getattr(previous, "detected_fields", {}) or {})
        current_fields = dict(getattr(current, "detected_fields", {}) or {})
        # Static hand facts must survive a transient weak frame. Dynamic values
        # such as bets, pot, actions and active seats deliberately stay fresh.
        for key in (
            "hero_cards",
            "board_card_1", "board_card_2", "board_card_3", "board_card_4", "board_card_5",
            "top_left_name", "top_right_name", "left_name", "right_name", "hero_name",
            "top_left_stack", "top_right_stack", "left_stack", "right_stack", "hero_stack",
            "dealer_button",
        ):
            if not current_fields.get(key) and previous_fields.get(key):
                current_fields[key] = previous_fields[key]

        old_board = str(getattr(previous, "visible_board", "") or "")
        new_board = str(getattr(current, "visible_board", "") or "")
        board = new_board if len(new_board.split()) >= len(old_board.split()) else old_board
        hero_cards = str(getattr(current, "hero_cards", "") or getattr(previous, "hero_cards", "") or "")
        board_count = len(board.split())
        street = "river" if board_count >= 5 else "turn" if board_count == 4 else "flop" if board_count >= 3 else "preflop"
        return replace(
            current,
            hero_cards=hero_cards,
            visible_board=board,
            current_street=street,
            detected_fields=current_fields,
        )

    @staticmethod
    def _board_signature(image_path: str) -> str:
        if not image_path:
            return ""
        try:
            image = Image.open(image_path).convert("L")
            zone = load_calibration().get("zones", {}).get("board")
            if zone:
                width, height = image.size
                rect = tuple(int(value * (width if index % 2 == 0 else height)) for index, value in enumerate(zone))
                image = image.crop(rect)
            image.thumbnail((96, 32))
            return hashlib.sha1(image.tobytes()).hexdigest()
        except (OSError, ValueError):
            return ""

    @staticmethod
    def _hero_signature(image_path: str) -> str:
        """Cheap visual key that prevents hero cards leaking into a new hand."""
        if not image_path:
            return ""
        try:
            image = Image.open(image_path).convert("L")
            zones = load_calibration().get("zones", {})
            digest = hashlib.sha1()
            for zone_name in ("hero_card_1_value", "hero_card_2_value"):
                zone = zones.get(zone_name)
                if not zone:
                    return ""
                width, height = image.size
                rect = tuple(
                    int(value * (width if index % 2 == 0 else height))
                    for index, value in enumerate(zone)
                )
                crop = image.crop(rect)
                crop.thumbnail((24, 32))
                digest.update(crop.tobytes())
            return digest.hexdigest()
        except (OSError, ValueError):
            return ""

    @staticmethod
    def _freeze_live_capture(image_path: str) -> str:
        """Copy the current frame before the background OCR starts reading it."""
        source = Path(image_path)
        if not source.exists():
            return ""
        target = source.with_name(f"{source.stem}_full.png")
        temporary = target.with_suffix(".tmp.png")
        try:
            with Image.open(source) as image:
                image.copy().save(temporary)
            temporary.replace(target)
            return str(target)
        except OSError:
            return ""

    def _render_live_decision(
        self,
        snapshot: object,
        full_ocr: bool,
        analysis_pending: bool = False,
        preserve_details: bool = False,
    ) -> None:
        if self.live_decision_text is None:
            return

        if snapshot is None:
            content = (
                "DEBUG LIVE\n\n"
                "ROBOT\n"
                "- Etat : recherche d'une table Winamax\n"
                "- Action : aucun traitement en cours\n"
            )
        else:
            hero_name = self._safe_live_hero_name(getattr(snapshot, "hero_name", ""))
            street = getattr(snapshot, "current_street", "") or "-"
            hero_cards = getattr(snapshot, "hero_cards", "") or "-"
            board = getattr(snapshot, "visible_board", "") or "-"
            pot = getattr(snapshot, "pot_text", "") or "-"
            actions = ", ".join(getattr(snapshot, "available_actions", []) or []) or "-"
            visual = ", ".join(getattr(snapshot, "visual_buttons", []) or []) or "-"
            detected_fields = getattr(snapshot, "detected_fields", {}) or {}
            players_in_hand = ", ".join(getattr(snapshot, "players_in_hand", []) or []) or "-"
            dealer = getattr(snapshot, "dealer_owner", "") or "-"
            hero_position = detected_fields.get("hero_position", "") or "-"
            stacks = self._format_live_stacks(detected_fields)
            hero_turn = bool(getattr(snapshot, "is_hero_turn", False))
            recommendation = getattr(snapshot, "recommendation", None)
            recommendation_text = getattr(recommendation, "summary", "") or "-"
            recommendation_confidence = float(getattr(recommendation, "confidence", 0.0) or 0.0)
            hand_strength = getattr(recommendation, "hand_strength", "") or "-"
            villain_range = getattr(recommendation, "villain_range", "") or "-"
            recommendation_reasons = " | ".join(getattr(recommendation, "reasons", []) or []) or "-"
            strategy_mix = getattr(recommendation, "strategy_mix", "") or "-"
            equity = getattr(recommendation, "equity", None)
            pot_odds = getattr(recommendation, "pot_odds", None)
            call_amount = getattr(recommendation, "call_amount", None)
            opponent_count = int(getattr(recommendation, "opponent_count", 0) or 0)
            effective_stack = getattr(recommendation, "effective_stack_bb", None)
            spr = getattr(recommendation, "spr", None)
            pot_type = getattr(recommendation, "pot_type", "") or "-"
            preflop_aggressor = getattr(recommendation, "preflop_aggressor", "") or "-"
            bluff_probability = getattr(recommendation, "bluff_success_probability", None)
            bluff_break_even = getattr(recommendation, "bluff_break_even_probability", None)
            bluff_ev = getattr(recommendation, "bluff_ev_bb", None)
            bluff_summary = getattr(recommendation, "bluff_summary", "") or "-"
            value_call_probability = getattr(recommendation, "value_call_probability", None)
            value_equity = getattr(recommendation, "value_equity_when_called", None)
            value_ev = getattr(recommendation, "value_ev_bb", None)
            value_summary = getattr(recommendation, "value_summary", "") or "-"
            equity_text = f"{equity:.1%}" if equity is not None else "-"
            odds_text = f"{pot_odds:.1%}" if pot_odds is not None else "-"
            call_text = f"{call_amount:g} BB" if call_amount is not None else "-"
            effective_stack_text = f"{effective_stack:g} BB" if effective_stack is not None else "-"
            spr_text = f"{spr:.2f}" if spr is not None else "-"
            bluff_probability_text = f"{bluff_probability:.0%}" if bluff_probability is not None else "-"
            bluff_break_even_text = f"{bluff_break_even:.0%}" if bluff_break_even is not None else "-"
            bluff_ev_text = f"{bluff_ev:+.2f} BB" if bluff_ev is not None else "-"
            value_call_text = f"{value_call_probability:.0%}" if value_call_probability is not None else "-"
            value_equity_text = f"{value_equity:.0%}" if value_equity is not None else "-"
            value_ev_text = f"{value_ev:+.2f} BB" if value_ev is not None else "-"
            history_actions = " | ".join(getattr(snapshot, "recent_actions", []) or []) or "-"
            active_profiles = [
                profile
                for profile in (getattr(snapshot, "villain_profiles", []) or [])
                if getattr(profile, "seat", "") in (getattr(snapshot, "players_in_hand", []) or [])
            ]
            effective_range_lines = list(getattr(recommendation, "villain_ranges", []) or [])
            if effective_range_lines:
                active_ranges = "\n".join(f"- {line}" for line in effective_range_lines)
            elif active_profiles:
                active_ranges = "\n".join(
                    "- "
                    f"{getattr(profile, 'name', getattr(profile, 'seat', 'vilain'))} "
                    f"({getattr(profile, 'seat', '-')}) : "
                    f"{getattr(profile, 'estimated_range', '-')}; "
                    f"profil {getattr(profile, 'profile', '-')}; "
                    f"{getattr(profile, 'hands_played', 0)} mains, "
                    f"VPIP {float(getattr(profile, 'vpip', 0.0)):.0%}, "
                    f"PFR {float(getattr(profile, 'pfr', 0.0)):.0%}"
                    for profile in active_profiles
                )
            else:
                active_ranges = "- Aucun adversaire actif détecté avec certitude."

            probability_lines = list(getattr(recommendation, "villain_hand_probabilities", []) or [])
            hand_probabilities = "\n".join(f"- {line}" for line in probability_lines) or "- Disponible a partir du flop."

            if hero_turn:
                if full_ocr:
                    robot_action = "Analyse complète terminée ; résultat conservé."
                else:
                    robot_action = "Tour hero détecté ; analyse complète en cours."
            else:
                robot_action = "Tour hero non détecté ; scan rapide poursuivi."
            if analysis_pending and not full_ocr:
                robot_action = "Tour hero détecté ; analyse complète mise en file."

            content = (
                "DEBUG LIVE\n\n"
                "ROBOT\n"
                f"- Action : {robot_action}\n"
                f"- Dernier scan : {self.last_live_scan_at or '-'}\n\n"
                "DÉTECTION\n"
                f"- Tour hero : {'oui' if hero_turn else 'non'}\n"
                f"- Joueur hero : {hero_name}\n"
                f"- Cartes hero : {hero_cards}\n"
                f"- Board : {board}\n"
                f"- Street : {street}\n"
                f"- Pot : {pot}\n"
                f"- Actions : {actions}\n"
                f"- Boutons actifs : {visual}\n"
                f"- Dealer : {dealer}\n"
                f"- Position hero : {hero_position}\n"
                f"- Stacks : {stacks}\n"
                f"- Joueurs actifs : {players_in_hand}\n"
                f"- Actions historique : {history_actions}\n\n"
                "RECOMMANDATION\n"
                f"- Decision : {recommendation_text}\n"
                f"- Strategie de base : {strategy_mix}\n"
                f"- Confiance : {recommendation_confidence:.0%}\n"
                f"- Force hero : {hand_strength}\n"
                f"- Range vilain : {villain_range}\n"
                f"- Type de pot : {pot_type}\n"
                f"- Agresseur preflop : {preflop_aggressor}\n"
                f"- Stack effectif : {effective_stack_text}\n"
                f"- SPR : {spr_text}\n"
                f"- Bluff : passage estime {bluff_probability_text}, seuil {bluff_break_even_text}, EV fold equity {bluff_ev_text}\n"
                f"- Detail bluff : {bluff_summary}\n"
                f"- Value bet : call estime {value_call_text}, equite si call {value_equity_text}, EV {value_ev_text}\n"
                f"- Detail value : {value_summary}\n"
                f"- Adversaires calculés : {opponent_count}\n"
                f"- Montant à payer : {call_text}\n"
                f"- Équité multiway : {equity_text}\n"
                f"- Cote minimale : {odds_text}\n"
                f"- Raisons : {recommendation_reasons}\n"
                "\nRANGES DES JOUEURS EN JEU\n"
                f"{active_ranges}\n"
                "\nREPARTITION POSTFLOP ESTIMEE\n"
                f"{hand_probabilities}\n"
            )

        self.live_decision_text.configure(state="normal")
        self.live_decision_text.delete("1.0", tk.END)
        self.live_decision_text.insert("1.0", content)
        self.live_decision_text.configure(state="disabled")
        self._render_table_decision_overlay(snapshot, full_ocr=full_ocr)
        self._render_player_range_overlays(snapshot, full_ocr=full_ocr)

    def _render_table_decision_overlay(self, snapshot: object, *, full_ocr: bool) -> None:
        """Show the verified recommendation beside the hero seat, click-through."""
        recommendation = getattr(snapshot, "recommendation", None) if snapshot is not None else None
        hero_turn = bool(getattr(snapshot, "is_hero_turn", False)) if snapshot is not None else False
        action = str(getattr(recommendation, "action", "") or "").upper()
        window = self.last_live_window
        if not full_ocr or not hero_turn or action in {"", "ATTENDRE"} or window is None:
            self._hide_table_decision_overlay()
            return

        overlay = self._ensure_table_decision_overlay()
        label = self.decision_overlay_label
        if overlay is None or label is None:
            return
        sizing = str(getattr(recommendation, "sizing", "") or "")
        call_amount = getattr(recommendation, "call_amount", None)
        detail = sizing
        if action == "CALL" and call_amount is not None:
            detail = f"{call_amount:g} BB"
        label.configure(
            text=f"{action}\n{detail}" if detail else action,
            fg={"FOLD": "#ff6b6b", "CALL": "#ffd166", "RAISE": "#69db7c", "BET": "#69db7c", "CHECK": "#74c0fc"}.get(action, "#ffffff"),
        )
        overlay.deiconify()
        overlay.update_idletasks()
        left, top, right, bottom = window.rect
        width, height = max(1, right - left), max(1, bottom - top)
        # To the right of the hero cards/name, above the native action bar.
        x = left + int(width * 0.575)
        y = top + int(height * 0.685)
        overlay.geometry(f"+{x}+{y}")
        overlay.lift()

    def _ensure_table_decision_overlay(self) -> tk.Toplevel | None:
        if self.decision_overlay is not None and self.decision_overlay.winfo_exists():
            return self.decision_overlay
        try:
            overlay = tk.Toplevel(self.root)
            overlay.withdraw()
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.attributes("-alpha", 0.94)
            overlay.configure(background="#10151f")
            label = tk.Label(
                overlay,
                background="#10151f",
                font=("Segoe UI", 14, "bold"),
                justify="center",
                padx=12,
                pady=6,
                relief="solid",
                borderwidth=1,
            )
            label.pack()
            self.decision_overlay = overlay
            self.decision_overlay_label = label
            self._make_window_click_through(overlay)
            return overlay
        except tk.TclError:
            return None

    @staticmethod
    def _make_window_click_through(window: tk.Toplevel) -> None:
        """Avoid stealing poker-table clicks on Windows."""
        try:
            hwnd = window.winfo_id()
            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW
            style = get_style(hwnd, -20)  # GWL_EXSTYLE
            set_style(hwnd, -20, style | 0x20 | 0x08000000)  # TRANSPARENT | NOACTIVATE
        except (AttributeError, OSError):
            pass

    def _hide_table_decision_overlay(self) -> None:
        if self.decision_overlay is not None and self.decision_overlay.winfo_exists():
            self.decision_overlay.withdraw()

    def _render_player_range_overlays(self, snapshot: object, *, full_ocr: bool) -> None:
        """Place the current action-adjusted range beside each active villain."""
        if snapshot is None:
            self._hide_player_range_overlays()
            return
        # Fast scans deliberately avoid recomputing ranges.  Keep the last
        # verified labels visible until the next full analysis updates them.
        if not full_ocr:
            return
        window = self.last_live_window
        recommendation = getattr(snapshot, "recommendation", None)
        if window is None or recommendation is None:
            self._hide_player_range_overlays()
            return
        active_seats = set(getattr(snapshot, "players_in_hand", []) or []) - {"hero"}
        range_by_seat: dict[str, str] = {}
        for line in getattr(recommendation, "villain_ranges", []) or []:
            match = re.search(r"\((top_left|top_right|left|right)\)\s*:\s*(.*?)\s*(?:\[|$)", str(line))
            if match:
                range_by_seat[match.group(1)] = match.group(2).strip()
        probabilities_by_seat: dict[str, str] = {}
        for line in getattr(recommendation, "villain_hand_probabilities", []) or []:
            match = re.search(r"\((top_left|top_right|left|right)\)\s*:\s*(.*)$", str(line))
            if match:
                probabilities_by_seat[match.group(1)] = match.group(2).strip()

        fields = getattr(snapshot, "detected_fields", {}) or {}
        anchors = {
            "top_left": (0.22, 0.135),
            "top_right": (0.66, 0.135),
            "left": (0.06, 0.575),
            "right": (0.77, 0.575),
        }
        left, top, right, bottom = window.rect
        width, height = max(1, right - left), max(1, bottom - top)
        visible: set[str] = set()
        for seat in active_seats:
            range_text = range_by_seat.get(seat, "")
            if not range_text or seat not in anchors:
                continue
            overlay, label = self._ensure_player_range_overlay(seat)
            name = str(fields.get(f"{seat}_name", "") or seat)
            probabilities = probabilities_by_seat.get(seat, "")
            probability_text = "\n".join(probabilities.split(" · "))
            label.configure(
                text=f"{name}\nRange : {range_text}" + (f"\n—\n{probability_text}" if probability_text else ""),
            )
            overlay.deiconify()
            overlay.update_idletasks()
            x_ratio, y_ratio = anchors[seat]
            overlay.geometry(f"+{left + int(width * x_ratio)}+{top + int(height * y_ratio)}")
            overlay.lift()
            visible.add(seat)
        for seat, (overlay, _label) in self.player_range_overlays.items():
            if seat not in visible and overlay.winfo_exists():
                overlay.withdraw()

    def _ensure_player_range_overlay(self, seat: str) -> tuple[tk.Toplevel, tk.Label]:
        existing = self.player_range_overlays.get(seat)
        if existing is not None and existing[0].winfo_exists():
            return existing
        overlay = tk.Toplevel(self.root)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.88)
        overlay.configure(background="#10151f")
        label = tk.Label(
            overlay,
            background="#10151f",
            foreground="#d7e3fc",
            font=("Segoe UI", 8, "bold"),
            justify="left",
            anchor="w",
            wraplength=230,
            padx=6,
            pady=3,
            relief="solid",
            borderwidth=1,
        )
        label.pack()
        self.player_range_overlays[seat] = (overlay, label)
        self._make_window_click_through(overlay)
        return overlay, label

    def _hide_player_range_overlays(self) -> None:
        for overlay, _label in self.player_range_overlays.values():
            if overlay.winfo_exists():
                overlay.withdraw()

    @staticmethod
    def _safe_live_hero_name(value: object) -> str:
        cleaned = " ".join(str(value or "").strip().split())
        lowered = cleaned.lower()
        if cleaned and len(cleaned) >= 4 and lowered not in {"sera", "hero", "voir", "tes", "cartes", "poser"}:
            return cleaned
        return "RougeLion"

    @staticmethod
    def _format_live_stacks(fields: dict[str, str]) -> str:
        parts = []
        for seat, name_field, stack_field in (
            ("top_left", "top_left_name", "top_left_stack"),
            ("top_right", "top_right_name", "top_right_stack"),
            ("left", "left_name", "left_stack"),
            ("right", "right_name", "right_stack"),
            ("hero", "hero_name", "hero_stack"),
        ):
            name = fields.get(name_field, "") or seat
            stack = fields.get(stack_field, "")
            if stack:
                parts.append(f"{name} {stack}")
        return " | ".join(parts) if parts else "-"

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
        if self.recording_in_progress:
            self._schedule_recording_poll()
        else:
            self._schedule_auto_recording(delay_ms=0)

    def _stop_auto_recording(self) -> None:
        self.is_recording = False
        if self._record_after_id is not None:
            self.root.after_cancel(self._record_after_id)
            self._record_after_id = None
        self.recording_session_var.set("Recording arrete.")

    def _schedule_auto_recording(self, delay_ms: int | None = None) -> None:
        if self._record_after_id is not None:
            self.root.after_cancel(self._record_after_id)
            self._record_after_id = None
        if self.is_recording:
            delay = self.record_interval_ms if delay_ms is None else delay_ms
            self._record_after_id = self.root.after(delay, self._auto_record_tick)

    def _auto_record_tick(self) -> None:
        self._record_after_id = None
        if not self.is_recording:
            return
        if self.recording_in_progress:
            self._schedule_recording_poll()
            return

        self.recording_in_progress = True
        self.pending_record_result = None
        self.recording_session_var.set("Recording actif | analyse du snapshot en arriere-plan...")

        def worker() -> None:
            try:
                snapshot = self.session_recorder.record_snapshot()
                self.pending_record_result = (snapshot, "")
            except Exception as exc:  # Keep the UI alive if one frame fails.
                self.pending_record_result = (None, str(exc))
            finally:
                self.recording_in_progress = False

        threading.Thread(target=worker, name="session-recorder", daemon=True).start()
        self._schedule_recording_poll()

    def _schedule_recording_poll(self) -> None:
        if self._record_after_id is not None:
            self.root.after_cancel(self._record_after_id)
        self._record_after_id = self.root.after(100, self._poll_recording_result)

    def _poll_recording_result(self) -> None:
        self._record_after_id = None
        result = self.pending_record_result
        if result is None:
            if self.recording_in_progress or self.is_recording:
                self._schedule_recording_poll()
            return

        self.pending_record_result = None
        snapshot, error = result
        if error:
            self.recording_session_var.set(f"Recording actif | erreur snapshot: {error}")
        elif snapshot is not None:
            self.recording_session_var.set(
                f"Recording actif | dernier snapshot: {snapshot.timestamp} | session {snapshot.session_id}"
            )
        elif self.is_recording:
            self.recording_session_var.set("Recording actif | aucune table Winamax detectee.")

        if self.is_recording:
            self._schedule_auto_recording()

    def _load_latest_session_review(self) -> None:
        sessions = self.session_recorder.list_sessions()
        if not sessions:
            messagebox.showinfo("Review", "Aucune session disponible.")
            return
        self.review_snapshots = self.session_recorder.list_snapshots(sessions[0])
        self.review_index = 0
        self._render_review_snapshot()

    def _load_element_review_samples(self) -> None:
        sessions = self.session_recorder.list_sessions()
        if not sessions:
            messagebox.showinfo("Review element", "Aucune session disponible.")
            return
        field = self.element_review_field_var.get()
        snapshots = self.session_recorder.list_snapshots(sessions[0])
        samples: list[dict] = []
        for snapshot in snapshots:
            payload = snapshot.get("payload", {})
            crop = self._build_element_crop(snapshot, field)
            if crop is None:
                continue
            detected_values = self._extract_detected_review_values(payload)
            review = snapshot.get("review", {}) or {}
            element_review = ((review.get("element_review") or {}).get(field) or {})
            samples.append(
                {
                    "snapshot": snapshot,
                    "field": field,
                    "crop": crop,
                    "detected": detected_values.get(field, "-"),
                    "saved_status": element_review.get("status", "unknown"),
                    "saved_expected": element_review.get("expected", ""),
                }
            )
        random.shuffle(samples)
        self.element_review_samples = samples
        self.element_review_index = 0
        self._render_element_review_sample()

    def _shuffle_element_review_samples(self) -> None:
        if not self.element_review_samples:
            self._load_element_review_samples()
            return
        random.shuffle(self.element_review_samples)
        self.element_review_index = 0
        self._render_element_review_sample()

    def _move_element_review(self, step: int) -> None:
        if not self.element_review_samples:
            return
        self.element_review_index = max(0, min(len(self.element_review_samples) - 1, self.element_review_index + step))
        self._render_element_review_sample()

    def _render_element_review_sample(self) -> None:
        if not self.element_review_samples or self.element_review_image_label is None:
            self.element_review_status_var.set("Aucun echantillon charge.")
            self.element_review_detected_var.set("-")
            self.element_review_choice_var.set("unknown")
            self.element_review_expected_var.set("")
            self.element_review_image_label.configure(text="Aucun echantillon charge.", image="")
            self.element_review_image_tk = None
            return

        sample = self.element_review_samples[self.element_review_index]
        image = sample["crop"].copy()
        image.thumbnail((980, 700))
        photo = ImageTk.PhotoImage(image)
        self.element_review_image_label.configure(image=photo, text="")
        self.element_review_image_label.image = photo
        self.element_review_image_tk = photo

        snapshot = sample["snapshot"]
        timestamp = (snapshot.get("payload") or {}).get("timestamp", "")
        current_detected = self._compute_current_element_detected(snapshot, sample["field"])
        sample["detected"] = current_detected
        self.element_review_status_var.set(
            f"{sample['field']} | echantillon {self.element_review_index + 1}/{len(self.element_review_samples)} | "
            f"{Path(snapshot.get('image_path') or '').name} | {timestamp}"
        )
        self.element_review_detected_var.set(current_detected)
        self.element_review_choice_var.set(sample.get("saved_status", "unknown"))
        self.element_review_expected_var.set(sample.get("saved_expected", ""))

    def _save_element_review_annotation(self) -> None:
        if not self.element_review_samples:
            return
        sample = self.element_review_samples[self.element_review_index]
        snapshot = sample["snapshot"]
        review_path = snapshot.get("review_path") or ""
        review_payload = snapshot.get("review", {}) or {}
        review_payload.setdefault("status", self.review_global_status_var.get())
        review_payload.setdefault("note", "")
        review_payload.setdefault("timestamp", (snapshot.get("payload") or {}).get("timestamp", ""))
        review_payload["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        review_payload.setdefault("fields", {})
        review_payload.setdefault("element_review", {})
        review_payload["element_review"][sample["field"]] = {
            "status": self.element_review_choice_var.get(),
            "expected": self.element_review_expected_var.get().strip(),
        }
        self.session_recorder.save_snapshot_review(review_path, review_payload)
        snapshot["review"] = review_payload
        sample["saved_status"] = self.element_review_choice_var.get()
        sample["saved_expected"] = self.element_review_expected_var.get().strip()
        self.element_review_status_var.set(
            f"Element sauvegarde | {sample['field']} | {self.element_review_index + 1}/{len(self.element_review_samples)}"
        )

    def _compute_current_element_detected(self, snapshot: dict, field: str) -> str:
        image_path = snapshot.get("image_path") or ""
        if not image_path or not Path(image_path).exists():
            return "-"
        try:
            ocr_snapshot = run_local_ocr_on_image(image_path)
        except Exception:
            return "-"

        payload = dict(snapshot.get("payload") or {})
        payload["ocr"] = {
            "status": ocr_snapshot.status,
            "engine_path": ocr_snapshot.engine_path,
            "text": ocr_snapshot.text,
            "zones": {
                name: {
                    "text": zone.text,
                    "rect": list(zone.rect),
                    "image_path": zone.image_path,
                }
                for name, zone in ocr_snapshot.zones.items()
            },
        }
        values = self._extract_detected_review_values(payload)
        return values.get(field, "-")

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
            review = snapshot.get("review", {})
            summary = {
                "index": self.review_index + 1,
                "total": len(self.review_snapshots),
                "timestamp": payload.get("timestamp", ""),
                "window": payload.get("window", {}),
                "history_file": payload.get("history_file", ""),
                "live_snapshot": payload.get("live_snapshot", {}),
                "review": review,
            }
            self.review_text.configure(state="normal")
            self.review_text.delete("1.0", tk.END)
            self.review_text.insert("1.0", json.dumps(summary, indent=2, ensure_ascii=False))
            self.review_text.configure(state="disabled")

        review = snapshot.get("review", {})
        status = review.get("status", "non annoté")
        note = review.get("note", "")
        saved_at = review.get("saved_at", "")
        if saved_at:
            self.review_status_var.set(f"Annotation sauvegardée | statut: {status} | {saved_at}")
        else:
            self.review_status_var.set(f"Annotation: {status}")
        self.review_global_status_var.set(review.get("status", "review_later"))
        self.review_note_var.set(note)
        detected = self._extract_detected_review_values(payload)
        for field in REVIEW_FIELDS:
            self.review_detected_vars[field].set(detected.get(field, "-"))
        field_reviews = review.get("fields", {})
        for field in REVIEW_FIELDS:
            field_data = field_reviews.get(field, {})
            if isinstance(field_data, str):
                self.review_field_vars[field].set(field_data)
                self.review_expected_vars[field].set("")
            else:
                self.review_field_vars[field].set(field_data.get("status", "unknown"))
                self.review_expected_vars[field].set(field_data.get("expected", ""))

    def _save_review_annotation(self) -> None:
        if not self.review_snapshots:
            return
        snapshot = self.review_snapshots[self.review_index]
        payload = snapshot.get("payload", {})
        review_payload = {
            "status": self.review_global_status_var.get(),
            "note": self.review_note_var.get().strip(),
            "timestamp": payload.get("timestamp", ""),
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fields": {
                field: {
                    "status": self.review_field_vars[field].get(),
                    "expected": self.review_expected_vars[field].get().strip(),
                }
                for field in REVIEW_FIELDS
            },
        }
        self.session_recorder.save_snapshot_review(snapshot["review_path"], review_payload)
        snapshot["review"] = review_payload
        self.review_status_var.set("Annotations sauvegardées.")
        self._render_review_snapshot()

    def _build_element_crop(self, snapshot: dict, field: str) -> Image.Image | None:
        image_path = snapshot.get("image_path") or ""
        if not image_path or not Path(image_path).exists():
            return None
        try:
            image = Image.open(image_path).convert("RGB")
        except OSError:
            return None

        calibration = load_calibration()
        zone_name = self._review_zone_name(field)
        zone_values = (calibration.get("zones") or {}).get(zone_name)
        if not zone_values or len(zone_values) != 4:
            return None
        width, height = image.size
        left = int(width * zone_values[0])
        top = int(height * zone_values[1])
        right = int(width * zone_values[2])
        bottom = int(height * zone_values[3])

        pad_x = max(8, int((right - left) * 0.15))
        pad_y = max(8, int((bottom - top) * 0.20))
        crop_box = (
            max(0, left - pad_x),
            max(0, top - pad_y),
            min(width, right + pad_x),
            min(height, bottom + pad_y),
        )
        crop = image.crop(crop_box)
        draw = ImageDraw.Draw(crop)
        inner_box = (
            left - crop_box[0],
            top - crop_box[1],
            right - crop_box[0],
            bottom - crop_box[1],
        )
        draw.rectangle(inner_box, outline="#ff5d5d", width=3)
        draw.rectangle((4, 4, min(crop.width - 4, 220), 28), fill=(20, 20, 20))
        draw.text((8, 7), FIELD_LABELS.get(field, field), fill="#ff5d5d")
        return crop

    @staticmethod
    def _review_zone_name(field: str) -> str:
        return FIELD_ZONE_MAP.get(field, field)

    @staticmethod
    def _extract_detected_review_values(payload: dict) -> dict[str, str]:
        live = payload.get("live_snapshot") or {}
        ocr = payload.get("ocr") or {}
        zones = ocr.get("zones") or {}

        def zone_text(name: str) -> str:
            return ((zones.get(name) or {}).get("text") or "").strip()

        def zone_image_path(name: str) -> str:
            return ((zones.get(name) or {}).get("image_path") or "").strip()

        board_text = zone_text("board")
        board_cards = PokerTrackerApp._extract_board_cards(board_text)
        card_zone_values = [
            PokerTrackerApp._normalize_card_value(zone_text("board_card_1")),
            PokerTrackerApp._normalize_card_value(zone_text("board_card_2")),
            PokerTrackerApp._normalize_card_value(zone_text("board_card_3")),
            PokerTrackerApp._normalize_card_value(zone_text("board_card_4")),
            PokerTrackerApp._normalize_card_value(zone_text("board_card_5")),
        ]

        def first_non_empty(*values: str) -> str:
            for value in values:
                if value and value != "-":
                    return value
            return ""

        values = {
            "top_left_cards_visible": PokerTrackerApp._detect_cards_visible(zone_image_path("top_left_cards")),
            "top_left_name": PokerTrackerApp._clean_ocr_text(zone_text("top_left_name")),
            "top_left_stack": PokerTrackerApp._clean_ocr_text(zone_text("top_left_stack")),
            "top_right_cards_visible": PokerTrackerApp._detect_cards_visible(zone_image_path("top_right_cards")),
            "top_right_name": PokerTrackerApp._clean_ocr_text(zone_text("top_right_name")),
            "top_right_stack": PokerTrackerApp._clean_ocr_text(zone_text("top_right_stack")),
            "left_cards_visible": PokerTrackerApp._detect_cards_visible(zone_image_path("left_cards")),
            "left_name": PokerTrackerApp._clean_ocr_text(zone_text("left_name")),
            "left_stack": PokerTrackerApp._clean_ocr_text(zone_text("left_stack")),
            "right_cards_visible": PokerTrackerApp._detect_cards_visible(zone_image_path("right_cards")),
            "right_name": PokerTrackerApp._clean_ocr_text(zone_text("right_name")),
            "right_stack": PokerTrackerApp._clean_ocr_text(zone_text("right_stack")),
            "hero_name": first_non_empty(
                PokerTrackerApp._clean_ocr_text(zone_text("hero_name")),
                live.get("hero_name", ""),
            ),
            "hero_stack": first_non_empty(
                PokerTrackerApp._clean_ocr_text(zone_text("hero_stack")),
                PokerTrackerApp._clean_ocr_text(zone_text("hero")),
            ),
            "hero_status": PokerTrackerApp._clean_ocr_text(zone_text("hero_status")),
            "pot_value": first_non_empty(
                PokerTrackerApp._clean_ocr_text(zone_text("pot_value")),
                live.get("pot_text", ""),
                PokerTrackerApp._clean_ocr_text(zone_text("pot")),
            ),
            "dealer_button": PokerTrackerApp._clean_ocr_text(zone_text("dealer_button")),
            "board_card_1": first_non_empty(card_zone_values[0], board_cards[0] if len(board_cards) > 0 else ""),
            "board_card_2": first_non_empty(card_zone_values[1], board_cards[1] if len(board_cards) > 1 else ""),
            "board_card_3": first_non_empty(card_zone_values[2], board_cards[2] if len(board_cards) > 2 else ""),
            "board_card_4": first_non_empty(card_zone_values[3], board_cards[3] if len(board_cards) > 3 else ""),
            "board_card_5": first_non_empty(card_zone_values[4], board_cards[4] if len(board_cards) > 4 else ""),
        }
        return {key: (value if value else "-") for key, value in values.items()}

    @staticmethod
    def _detect_cards_visible(image_path: str) -> str:
        if not image_path or not Path(image_path).exists():
            return "-"
        try:
            image = Image.open(image_path).convert("RGB")
        except OSError:
            return "-"

        pixels = list(image.getdata())
        total = max(1, len(pixels))
        red_ratio = sum(1 for r, g, b in pixels if r > 120 and r > g * 1.2 and r > b * 1.2) / total
        bright_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 > 160) / total
        dark_ratio = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 40) / total

        if red_ratio > 0.06 or bright_ratio > 0.20:
            return "visible"
        if dark_ratio > 0.70:
            return "not_visible"
        return "uncertain"

    @staticmethod
    def _extract_board_cards(board_text: str) -> list[str]:
        cleaned = (
            board_text.replace("\n", " ")
            .replace(",", " ")
            .replace("|", " ")
            .replace("10", "T")
            .replace("O", "Q")
        )
        tokens = [token.strip() for token in cleaned.split() if token.strip()]

        cards: list[str] = []
        for token in tokens:
            token = token.lower()
            if len(token) == 2 and token[0] in "a23456789tjqk" and token[1] in "shdc":
                cards.append(token)
                continue
            if len(token) == 1 and token in "a23456789tjqk":
                cards.append(token)

        while len(cards) < 5:
            cards.append("")
        return cards[:5]

    @staticmethod
    def _clean_ocr_text(value: str) -> str:
        return " ".join(part.strip() for part in value.splitlines() if part.strip()).strip()

    @staticmethod
    def _normalize_card_value(value: str) -> str:
        token = PokerTrackerApp._clean_ocr_text(value).lower().replace("10", "t")
        token = token.replace(" ", "")
        if len(token) >= 2 and token[0] in "a23456789tjqk" and token[1] in "shdc":
            return token[:2]
        return ""

    def _save_calibration(self) -> None:
        zones: dict[str, list[float]] = {}
        try:
            for name, vars_for_zone in self.calibration_entries.items():
                display_values = [float(var.get().replace(",", ".")) for var in vars_for_zone]
                if len(display_values) != 4:
                    raise ValueError(name)
                left, top, width, height = display_values
                right = left + width
                bottom = top + height
                if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                    raise ValueError(name)
                zones[name] = [left, top, right, bottom]
        except ValueError as exc:
            messagebox.showerror("Calibration invalide", f"Valeurs invalides pour la zone {exc}.")
            return

        save_calibration({"zones": zones})
        messagebox.showinfo("Calibration", "Calibration enregistree.")
        self._redraw_calibration_preview()

    def _reload_calibration(self) -> None:
        calibration = load_calibration()
        for name, values in calibration.get("zones", {}).items():
            left, top, right, bottom = values
            display_values = [left, top, max(0.0, right - left), max(0.0, bottom - top)]
            for var, value in zip(self.calibration_entries.get(name, []), display_values, strict=True):
                var.set(f"{value:.2f}")
        self._redraw_calibration_preview()

    def _reset_calibration_defaults(self) -> None:
        defaults = DEFAULT_CALIBRATION.get("zones", {})
        for name, values in defaults.items():
            left, top, right, bottom = values
            display_values = [left, top, max(0.0, right - left), max(0.0, bottom - top)]
            for var, value in zip(self.calibration_entries.get(name, []), display_values, strict=True):
                var.set(f"{value:.2f}")
        self._redraw_calibration_preview()

    def _refresh_calibration_preview(self) -> None:
        self.calibration_snapshots = []
        self.calibration_index = 0
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
                self.calibration_status_var.set("Aucune capture disponible.")
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
                self.calibration_status_var.set("Capture impossible.")
                return

        self.last_preview_source_path = image_path
        self.calibration_status_var.set(f"Image calibration: {Path(image_path).name}")
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
            self.calibration_status_var.set("Aucune capture disponible.")
            return

        preview = self._build_calibration_preview_image(image_path)
        photo = ImageTk.PhotoImage(preview)
        self.calibration_preview_label.configure(image=photo, text="")
        self.calibration_preview_label.image = photo
        self.calibration_preview_image = photo
        self.calibration_status_var.set(f"Blocs appliqués sur: {Path(image_path).name}")

    def _on_calibration_var_changed(self, *_args: object) -> None:
        self._schedule_calibration_redraw()

    def _schedule_calibration_redraw(self) -> None:
        if self._calibration_redraw_after_id is not None:
            self.root.after_cancel(self._calibration_redraw_after_id)
            self._calibration_redraw_after_id = None
        self._calibration_redraw_after_id = self.root.after(120, self._flush_calibration_redraw)

    def _flush_calibration_redraw(self) -> None:
        self._calibration_redraw_after_id = None
        self._redraw_calibration_preview()

    def _load_latest_calibration_session(self) -> None:
        sessions = self.session_recorder.list_sessions()
        if not sessions:
            messagebox.showinfo("Calibration", "Aucune session disponible.")
            return
        self.calibration_snapshots = self.session_recorder.list_snapshots(sessions[0])
        self.calibration_index = 0
        self._render_calibration_snapshot()

    def _move_calibration_image(self, step: int) -> None:
        if not self.calibration_snapshots:
            return
        self.calibration_index = max(0, min(len(self.calibration_snapshots) - 1, self.calibration_index + step))
        self._render_calibration_snapshot()

    def _render_calibration_snapshot(self) -> None:
        if not self.calibration_snapshots:
            return
        snapshot = self.calibration_snapshots[self.calibration_index]
        image_path = snapshot.get("image_path") or ""
        if not image_path:
            self.calibration_status_var.set("Snapshot sans image.")
            return
        self.last_preview_source_path = image_path
        preview = self._build_calibration_preview_image(image_path)
        photo = ImageTk.PhotoImage(preview)
        if self.calibration_preview_label is not None:
            self.calibration_preview_label.configure(image=photo, text="")
            self.calibration_preview_label.image = photo
        self.calibration_preview_image = photo
        self.calibration_status_var.set(
            f"Session image {self.calibration_index + 1}/{len(self.calibration_snapshots)}: {Path(image_path).name}"
        )

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
                left, top, width_ratio, height_ratio = [float(var.get().replace(",", ".")) for var in vars_for_zone]
                zones[name] = [left, top, left + width_ratio, top + height_ratio]
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
            draw.text((left + 6, top + 5), CALIBRATION_LABELS.get(name, name), fill=color)

        preview = image.copy()
        preview = ImageEnhance.Brightness(preview).enhance(1.15)
        preview = ImageEnhance.Contrast(preview).enhance(1.15)
        max_width = 1120
        max_height = 760
        if self.calibration_preview_label is not None:
            widget_width = max(200, self.calibration_preview_label.winfo_width() - 12)
            widget_height = max(200, self.calibration_preview_label.winfo_height() - 12)
            max_width = max(200, min(1400, widget_width))
            max_height = max(200, min(900, widget_height))
        preview.thumbnail((max_width, max_height))
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
        if self.decision_overlay is not None and self.decision_overlay.winfo_exists():
            self.decision_overlay.destroy()
        for overlay, _label in self.player_range_overlays.values():
            if overlay.winfo_exists():
                overlay.destroy()
        self.root.destroy()


def main() -> None:
    app = PokerTrackerApp()
    app.run()
