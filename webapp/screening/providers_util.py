"""Deteta que providers estao disponiveis (chave no .env ou Ollama a responder)."""

from __future__ import annotations

import os
import socket
from typing import Dict, List

from screening_core import PROVIDERS


def _ollama_reachable(host: str = "localhost", port: int = 11434, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def available_providers() -> List[Dict[str, object]]:
    """Lista de providers com flag de disponibilidade e motivo."""
    out: List[Dict[str, object]] = []
    for key, meta in PROVIDERS.items():
        if key == "ollama":
            ok = _ollama_reachable()
            reason = "" if ok else "Ollama nao responde em localhost:11434 (corre 'ollama serve')."
        else:
            ok = bool(os.getenv(meta["key_env"], ""))
            reason = "" if ok else "Falta {} no pipeline/.env.".format(meta["key_env"])
        out.append({
            "key": key,
            "label": meta["label"],
            "default_model": meta["default_model"],
            "available": ok,
            "reason": reason,
        })
    return out


def available_keys() -> List[str]:
    return [p["key"] for p in available_providers() if p["available"]]
