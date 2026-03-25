from __future__ import annotations

import json
import random
import tkinter as tk
from datetime import datetime
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
REVIEW_FIELDS = [
    "top_left_cards_visible",
    "top_left_name",
    "top_left_stack",
    "top_right_cards_visible",
    "top_right_name",
    "top_right_stack",
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
        self.refresh_ms = 5000
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
        self._create_element_review_tab(notebook)

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
        self.element_review_status_var.set(
            f"{sample['field']} | echantillon {self.element_review_index + 1}/{len(self.element_review_samples)} | "
            f"{Path(snapshot.get('image_path') or '').name} | {timestamp}"
        )
        self.element_review_detected_var.set(sample.get("detected", "-"))
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
        payload = snapshot.get("payload") or {}
        zones = ((payload.get("ocr") or {}).get("zones") or {})
        zone = zones.get(self._review_zone_name(field)) or {}
        rect = zone.get("rect") or []
        if len(rect) != 4:
            return None
        try:
            left, top, right, bottom = [int(value) for value in rect]
            image = Image.open(image_path).convert("RGB")
        except (OSError, ValueError):
            return None

        width, height = image.size
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
        self.root.destroy()


def main() -> None:
    app = PokerTrackerApp()
    app.run()
