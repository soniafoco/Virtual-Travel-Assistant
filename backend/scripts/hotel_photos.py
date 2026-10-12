"""Foto degli hotel: legge scripts/hotel_photos.json (creato da fetch_hotel_photos.py).

Il seed le usa quando crea gli hotel. Se cambiano le foto va rifatto il seed (python -m scripts.seed).
"""

import json
from pathlib import Path

FILE_FOTO = Path(__file__).parent / "hotel_photos.json"


def carica_foto() -> dict:
    """Le foto trovate, per nome dell'hotel: {nome: {"image_url": ..., "image_credit": ...}}. Vuoto se il file non c'e'."""
    if not FILE_FOTO.exists():
        return {}
    return json.loads(FILE_FOTO.read_text(encoding="utf-8"))
