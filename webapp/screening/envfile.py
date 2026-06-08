"""Leitura/escrita das chaves de API no pipeline/.env (para o ecra de Definicoes)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from django.conf import settings

# Chaves geridas pela UI.
MANAGED_KEYS = [
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "NCBI_API_KEY",
    "NCBI_EMAIL",
]


def env_path() -> Path:
    return Path(settings.PIPELINE_DIR) / ".env"


def read_env() -> Dict[str, str]:
    """Le o .env como dict (so KEY=VALUE simples)."""
    path = env_path()
    data: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def write_env(updates: Dict[str, str]) -> None:
    """
    Atualiza/insere as chaves dadas no .env, preservando o resto do ficheiro,
    e aplica-as imediatamente em os.environ (o worker le os.getenv em runtime).
    Apenas valores nao-vazios sao escritos (vazio = manter o atual).
    """
    updates = {k: v for k, v in updates.items() if v}
    if not updates:
        return
    path = env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    out = []
    for line in lines:
        s = line.strip()
        if "=" in s and not s.startswith("#"):
            key = s.split("=", 1)[0].strip()
            if key in updates:
                out.append("{}={}".format(key, updates[key]))
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append("{}={}".format(key, value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")

    # Aplica de imediato (screening le os.getenv a cada chamada).
    for key, value in updates.items():
        os.environ[key] = value


def masked_status() -> Dict[str, str]:
    """Para mostrar na UI se cada chave esta definida (sem revelar o valor)."""
    current = read_env()
    status: Dict[str, str] = {}
    for key in MANAGED_KEYS:
        val = os.getenv(key, "") or current.get(key, "")
        if not val:
            status[key] = "nao definido"
        elif key == "NCBI_EMAIL":
            status[key] = val
        else:
            status[key] = "definido ({}...)".format(val[:4])
    return status
