from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from .config import CALIBRATION_FILE, load_calibration, save_calibration
from .session_recorder import SessionRecorder

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


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

SEAT_FIELDS = {
    "top_left_cards_visible": "top_left",
    "top_left_name": "top_left",
    "top_left_stack": "top_left",
    "top_right_cards_visible": "top_right",
    "top_right_name": "top_right",
    "top_right_stack": "top_right",
    "right_cards_visible": "right",
    "right_name": "right",
    "right_stack": "right",
    "hero_name": "hero",
    "hero_stack": "hero",
    "hero_status": "hero",
}

FIELD_TO_ZONE = {
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
    "pot_value": "pot_value",
    "dealer_button": "dealer_button",
    "board_card_1": "board_card_1",
    "board_card_2": "board_card_2",
    "board_card_3": "board_card_3",
    "board_card_4": "board_card_4",
    "board_card_5": "board_card_5",
}

PLAYER_HELP = (
    "Positions utiles: top_left = joueur en haut a gauche, top_right = joueur en haut a droite, "
    "right = joueur a droite, hero = joueur en bas."
)


@dataclass(slots=True)
class AnnotationResult:
    snapshot_path: Path
    annotation_path: Path
    review_path: Path
    seats: dict[str, dict[str, Any]]
    fields: dict[str, dict[str, Any]]


FIELD_MIN_CONFIDENCE = {
    "top_left_cards_visible": 0.75,
    "top_left_name": 0.8,
    "top_left_stack": 0.7,
    "top_right_cards_visible": 0.75,
    "top_right_name": 0.8,
    "top_right_stack": 0.7,
    "right_cards_visible": 0.75,
    "right_name": 0.8,
    "right_stack": 0.7,
    "hero_name": 0.9,
    "hero_stack": 0.9,
    "hero_status": 0.7,
    "pot_value": 0.7,
    "dealer_button": 0.8,
    "board_card_1": 0.8,
    "board_card_2": 0.8,
    "board_card_3": 0.8,
    "board_card_4": 0.8,
    "board_card_5": 0.8,
}


def annotate_session_with_openai(
    session_dir: Path,
    *,
    model: str = "gpt-5",
    limit: int | None = None,
    overwrite_annotation: bool = False,
    overwrite_review_expected: bool = False,
    apply_calibration: bool = False,
) -> list[AnnotationResult]:
    recorder = SessionRecorder(session_dir.parent)
    snapshots = recorder.list_snapshots(session_dir)
    if limit is not None:
        snapshots = snapshots[:limit]

    client = _build_openai_client()
    results: list[AnnotationResult] = []

    for snapshot in snapshots:
        image_path = Path(snapshot["image_path"])
        if not image_path.exists():
            continue

        annotation_path = image_path.with_suffix(".openai.json")
        if annotation_path.exists() and not overwrite_annotation:
            annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        else:
            annotation_payload = annotate_snapshot_with_openai(
                client=client,
                image_path=image_path,
                metadata=snapshot.get("payload", {}),
                model=model,
            )
            annotation_path.write_text(json.dumps(annotation_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        review_path = Path(snapshot["review_path"])
        review_payload = merge_openai_annotation_into_review(
            review_path=review_path,
            annotation_payload=annotation_payload,
            overwrite_expected=overwrite_review_expected,
        )
        review_path.write_text(json.dumps(review_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        results.append(
            AnnotationResult(
                snapshot_path=image_path,
                annotation_path=annotation_path,
                review_path=review_path,
                seats=annotation_payload.get("seats", {}),
                fields=annotation_payload["fields"],
            )
        )

    suggestion = build_calibration_suggestion_from_annotations(results)
    suggestion_path = session_dir / "openai_calibration.suggested.json"
    suggestion_path.write_text(json.dumps(suggestion, indent=2, ensure_ascii=False), encoding="utf-8")

    if apply_calibration:
        save_calibration(suggestion)

    return results


def annotate_snapshot_with_openai(
    *,
    client: Any,
    image_path: Path,
    metadata: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    image_data_url = _image_to_data_url(image_path)
    metadata_text = json.dumps(
        {
            "window": metadata.get("window", {}),
            "history_file": metadata.get("history_file", ""),
            "live_snapshot": metadata.get("live_snapshot", {}),
            "ocr_hint": _compact_ocr_hints(metadata.get("ocr", {})),
        },
        ensure_ascii=False,
        indent=2,
    )

    response = client.responses.create(
        model=model,
        store=False,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": _build_annotation_prompt(metadata_text)},
                    {"type": "input_image", "image_url": image_data_url, "detail": "high"},
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "poker_table_annotation",
                "strict": True,
                "schema": _annotation_schema(),
            }
        },
    )

    content = getattr(response, "output_text", "") or ""
    if not content:
        raise RuntimeError("La reponse OpenAI est vide.")

    payload = json.loads(content)
    payload["model"] = getattr(response, "model", model)
    payload["image_path"] = str(image_path)
    return payload


def merge_openai_annotation_into_review(
    *,
    review_path: Path,
    annotation_payload: dict[str, Any],
    overwrite_expected: bool,
) -> dict[str, Any]:
    if review_path.exists():
        try:
            review_payload = json.loads(review_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            review_payload = {}
    else:
        review_payload = {}

    review_payload.setdefault("status", "review_later")
    review_payload.setdefault("note", "")
    review_payload["openai_model"] = annotation_payload.get("model", "")
    review_payload["openai_summary"] = annotation_payload.get("summary", "")
    review_payload["openai_flags"] = annotation_payload.get("flags", [])
    review_payload["openai_seats"] = annotation_payload.get("seats", {})
    review_payload["fields"] = review_payload.get("fields", {})

    for field in REVIEW_FIELDS:
        existing = review_payload["fields"].get(field, {})
        if isinstance(existing, str):
            existing = {"status": existing, "expected": ""}

        incoming = annotation_payload["fields"].get(field, {})
        expected = (incoming.get("value") or "").strip()
        if overwrite_expected or not existing.get("expected"):
            existing["expected"] = expected
        existing.setdefault("status", "unknown")
        existing["openai_value"] = expected
        existing["openai_visible"] = bool(incoming.get("visible", False))
        existing["openai_confidence"] = float(incoming.get("confidence", 0.0) or 0.0)
        existing["openai_box"] = incoming.get("box")
        seat_name = SEAT_FIELDS.get(field)
        if seat_name:
            seat_payload = (annotation_payload.get("seats", {}) or {}).get(seat_name, {})
            existing["openai_seat_state"] = seat_payload.get("state", "")
        review_payload["fields"][field] = existing

    return review_payload


def build_calibration_suggestion_from_annotations(results: list[AnnotationResult]) -> dict[str, Any]:
    calibration = load_calibration()
    suggested = {"zones": dict(calibration.get("zones", {}))}
    buckets: dict[str, list[list[float]]] = {}

    for result in results:
        for field, zone_name in FIELD_TO_ZONE.items():
            field_payload = result.fields.get(field, {})
            box = field_payload.get("box")
            if not field_payload.get("visible") or not _valid_box(box):
                continue
            confidence = float(field_payload.get("confidence", 0.0) or 0.0)
            if confidence < FIELD_MIN_CONFIDENCE.get(field, 0.75):
                continue
            if not _seat_allows_field(result.seats, field):
                continue
            buckets.setdefault(zone_name, []).append(
                [box["left"], box["top"], box["right"], box["bottom"]]
            )

    for zone_name, values in buckets.items():
        suggested["zones"][zone_name] = [
            round(median(item[0] for item in values), 4),
            round(median(item[1] for item in values), 4),
            round(median(item[2] for item in values), 4),
            round(median(item[3] for item in values), 4),
        ]

    suggested["source"] = "openai_annotation_aggregate"
    suggested["source_file"] = str(CALIBRATION_FILE)
    return suggested


def _build_openai_client() -> Any:
    _load_project_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY est manquante.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Le package openai n'est pas installe. Lance `pip install -e .`.") from exc

    return OpenAI(api_key=api_key)


def _load_project_dotenv() -> None:
    if load_dotenv is None:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _build_annotation_prompt(metadata_text: str) -> str:
    return (
        "Tu analyses un screenshot unique de table de poker Winamax en 6-max. "
        "Reponds uniquement avec le JSON demande par le schema.\n\n"
        "Objectif:\n"
        "- detecter les elements de table utilises par notre systeme de review;\n"
        "- pour chaque champ, renvoyer la valeur lue et sa boite en ratios relatifs de l'image;\n"
        "- les ratios sont left, top, right, bottom entre 0.0 et 1.0;\n"
        "- si un element n'est pas visible, mettre visible=false, value='', box=null.\n\n"
        f"{PLAYER_HELP}\n"
        "La table a 4 sieges d'interet pour notre outil: top_left, top_right, right, hero.\n"
        "Chaque siege peut etre dans un etat parmi: present, absent, sitout, unknown.\n"
        "Tu dois d'abord raisonner siege par siege.\n"
        "Si un siege est absent, vide, ferme, ou sans joueur lisible, ne pas inventer de pseudo, stack ou cartes.\n"
        "Si tu n'es pas sur, utilise state='unknown' et laisse les champs non visibles vides.\n"
        "Regles de remplissage:\n"
        "- top_left_cards_visible / top_right_cards_visible / right_cards_visible: value doit etre visible, not_visible ou uncertain.\n"
        "- top_left_name / top_right_name / right_name / hero_name: pseudo du joueur.\n"
        "- stacks et pot_value: garder le texte lisible tel qu'affiche, ex: '102,7 BB' ou 'Pot : 2 BB'.\n"
        "- dealer_button: mettre de preference le nom du joueur proprietaire du bouton dealer, sinon une position.\n"
        "- board_card_1..5: format court type '7h', 'Qc', '3s'.\n"
        "- hero_status: texte comme ABSENT si visible.\n"
        "- confidence: nombre entre 0 et 1.\n\n"
        "Contraintes anti-hallucination:\n"
        "- n'invente jamais un pseudo, un stack, une carte ou un dealer si ce n'est pas visible;\n"
        "- si une carte vilain n'est pas clairement visible, mets value='not_visible' ou 'uncertain';\n"
        "- si un stack n'est pas lisible, mets visible=false.\n\n"
        "Contexte local utile (peut contenir du bruit OCR, a utiliser comme indice seulement):\n"
        f"{metadata_text}"
    )


def _annotation_schema() -> dict[str, Any]:
    field_properties = {}
    for field in REVIEW_FIELDS:
        field_properties[field] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "value": {"type": "string"},
                "visible": {"type": "boolean"},
                "confidence": {"type": "number"},
                "box": {
                    "anyOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "left": {"type": "number"},
                                "top": {"type": "number"},
                                "right": {"type": "number"},
                                "bottom": {"type": "number"},
                            },
                            "required": ["left", "top", "right", "bottom"],
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": ["value", "visible", "confidence", "box"],
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "flags": {"type": "array", "items": {"type": "string"}},
            "seats": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "top_left": _seat_schema(),
                    "top_right": _seat_schema(),
                    "right": _seat_schema(),
                    "hero": _seat_schema(),
                },
                "required": ["top_left", "top_right", "right", "hero"],
            },
            "fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": field_properties,
                "required": REVIEW_FIELDS,
            },
        },
        "required": ["summary", "flags", "seats", "fields"],
    }


def _compact_ocr_hints(ocr_payload: dict[str, Any]) -> dict[str, str]:
    zones = (ocr_payload or {}).get("zones", {}) or {}
    hints: dict[str, str] = {}
    for name, zone in zones.items():
        text = " ".join(((zone or {}).get("text") or "").split())
        if text:
            hints[name] = text[:120]
    return hints


def _image_to_data_url(image_path: Path) -> str:
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _valid_box(box: Any) -> bool:
    if not isinstance(box, dict):
        return False
    try:
        left = float(box["left"])
        top = float(box["top"])
        right = float(box["right"])
        bottom = float(box["bottom"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= left < right <= 1 and 0 <= top < bottom <= 1


def _seat_allows_field(seats: dict[str, dict[str, Any]], field: str) -> bool:
    seat_name = SEAT_FIELDS.get(field)
    if not seat_name:
        return True
    seat_payload = seats.get(seat_name, {}) if isinstance(seats, dict) else {}
    state = seat_payload.get("state", "unknown")
    return state in {"present", "sitout"}


def _seat_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "state": {"type": "string", "enum": ["present", "absent", "sitout", "unknown"]},
            "player_name": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["state", "player_name", "confidence"],
    }
