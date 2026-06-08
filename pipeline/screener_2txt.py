"""
screener_2txt.py
Versao V2 do screener: 2 ficheiros (system_RV*.txt + AbstractTexts/*.txt).
Envia 2 mensagens chat distintas: system (instrucao+criterios) + user (title+abstract).

Caracteristicas:
  - Estrutura: [system message] + [user message] (estilo Dennstadt 2024)
  - O system contem instrucao + criterios (fixo para toda a SR)
  - O user contem so title + abstract (varia por artigo)
  - Suporta provider: openai | groq | ollama
  - Output: mesmos ficheiros que screener.py screen
                 out/<tag>_condensed.txt, out/<tag>_full.txt,
                 out/<tag>_criteria.txt, out/<tag>_prompt_example.txt

Uso:
    python screener_2txt.py --input AbstractTexts/RV3.txt \\
                            --system system_RV3.txt \\
                            --tag RV3_v2

Para correr local com Ollama:
    python screener_2txt.py --input AbstractTexts/RV3.txt \\
                            --system system_RV3.txt \\
                            --tag RV3_v2_qwen3 \\
                            --provider ollama --model qwen3:8b \\
                            --no-think --sleep 0 --max-tokens 100

NOTA: para a versao V1 (single user message, 3 ficheiros), usa screener_3txt.py.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI


PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-2024-11-20",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": "OLLAMA_API_KEY",
        "default_model": "qwen3:8b",
    },
}

RECORD_RE = re.compile(
    r"Title:\s*(?P<title>.*?)\n"
    r"Abstract:\s*(?P<abstract>.*?)\n"
    r"Label Included:\s*(?P<label>[01])",
    flags=re.DOTALL,
)


def load_records(path: Path):
    text = path.read_text(encoding="utf-8")
    records = []
    for m in RECORD_RE.finditer(text):
        records.append({
            "title": m.group("title").strip(),
            "abstract": m.group("abstract").strip(),
            "label": int(m.group("label")),
        })
    if not records:
        sys.exit(f"[erro] Nenhum registo em {path}. Verifica formato Title/Abstract/Label Included.")
    return records


def yes_no_to_binary(token: str) -> Optional[int]:
    t = token.strip().lower().rstrip(".,;:")
    if t == "yes":
        return 1
    if t == "no":
        return 0
    return None


def parse_response(text: str):
    tokens = [yes_no_to_binary(line) for line in text.splitlines() if line.strip()]
    tokens = [t for t in tokens if t is not None]
    if not tokens:
        return None, []
    return tokens[0], tokens[1:]


def parse_args():
    p = argparse.ArgumentParser(
        prog="screener_2txt",
        description="V2: 2 ficheiros (system_RV*.txt + abstracts) -> system+user messages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input", required=True, help="AbstractTexts/<tag>.txt")
    p.add_argument("--system", required=True,
                   help="system_RV*.txt (baseprompt + criteria pre-concatenados)")
    p.add_argument("--tag", required=True, help="Identificador (ex: RV3_v2, RV3_v2_qwen3)")
    p.add_argument("--provider", choices=list(PROVIDERS.keys()), default="openai")
    p.add_argument("--model", default=None, help="Override (default depende do provider)")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-tokens", type=int, default=4000)
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--outdir", default="out")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--no-think", action="store_true", help="Desliga thinking mode (qwen3)")
    p.add_argument("--dry-run", action="store_true",
                   help="So gera prompt_example.txt e sai (nao chama LLM)")
    return p.parse_args()


def main():
    args = parse_args()
    load_dotenv()
    prov = PROVIDERS[args.provider]
    api_key = os.getenv(prov["key_env"])
    if not api_key:
        api_key = "ollama" if args.provider == "ollama" else sys.exit(
            f"[erro] {prov['key_env']} nao definida no .env"
        )
    model = args.model or prov["default_model"]
    print(f"[info] V2 (system+user)  provider={args.provider}  model={model}  system={args.system}")

    system_content = Path(args.system).read_text(encoding="utf-8").strip()
    records = load_records(Path(args.input))
    if args.limit > 0:
        records = records[: args.limit]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    f_full = f_cond = f_crit = None
    use_ollama_native = args.provider == "ollama"
    is_deepseek = args.provider == "deepseek"
    client = None if use_ollama_native else OpenAI(api_key=api_key, base_url=prov["base_url"])

    total_tokens, t0 = 0, time.time()

    for idx, rec in enumerate(records):
        if idx < args.start:
            continue

        # V2: system + user separados.
        user_content = f"Title: {rec['title']}\n\nAbstract: {rec['abstract']}"

        if idx == args.start:
            example_path = outdir / f"{args.tag}_prompt_example.txt"
            example_path.write_text(
                f"========== V2: MESSAGE 1 - SYSTEM ==========\n{system_content}\n\n"
                f"========== V2: MESSAGE 2 - USER ==========\n{user_content}\n",
                encoding="utf-8",
            )
            if args.dry_run:
                print(f"[dry-run] Prompt example -> {example_path}")
                return
            mode = "a" if args.start > 0 else "w"
            f_full = (outdir / f"{args.tag}_full.txt").open(mode, encoding="utf-8")
            f_cond = (outdir / f"{args.tag}_condensed.txt").open(mode, encoding="utf-8")
            f_crit = (outdir / f"{args.tag}_criteria.txt").open(mode, encoding="utf-8")
            if args.start == 0:
                f_cond.write("idx\tpred\tgold\n")

        sys_msg = system_content
        # /no_think e' uma directiva do qwen3; para deepseek desliga-se via extra_body.
        if args.no_think and not use_ollama_native and not is_deepseek:
            sys_msg = "/no_think\n" + sys_msg
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_content},
        ]
        try:
            if use_ollama_native:
                payload = {
                    "model": model, "messages": messages, "stream": False,
                    "options": {"temperature": args.temperature, "num_predict": args.max_tokens},
                }
                if args.no_think:
                    payload["think"] = False
                r = requests.post("http://localhost:11434/api/chat", json=payload, timeout=300)
                r.raise_for_status()
                data = r.json()
                content = data.get("message", {}).get("content", "") or ""
                total_tokens += (data.get("prompt_eval_count", 0) or 0) + (data.get("eval_count", 0) or 0)
            else:
                extra = {}
                if is_deepseek and args.no_think:
                    extra["extra_body"] = {"thinking": {"type": "disabled"}}
                resp = client.chat.completions.create(
                    model=model, messages=messages,
                    temperature=args.temperature, max_tokens=args.max_tokens, top_p=1,
                    **extra,
                )
                content = resp.choices[0].message.content or ""
                total_tokens += getattr(resp.usage, "total_tokens", 0) or 0
        except Exception as e:
            print(f"[{idx}] erro API: {e}", file=sys.stderr)
            time.sleep(args.sleep * 5)
            continue

        overall, per_criterion = parse_response(content)
        pred = overall if overall is not None else -1
        f_full.write(f"=== idx={idx} gold={rec['label']} ===\n")
        f_full.write(f"Title: {rec['title']}\nAbstract: {rec['abstract']}\n")
        f_full.write(f"--- response ---\n{content}\n\n")
        f_cond.write(f"{idx}\t{pred}\t{rec['label']}\n")
        f_crit.write(f"=== idx={idx} gold={rec['label']} overall={pred} ===\n")
        for j, c in enumerate(per_criterion):
            f_crit.write(f"crit_{j}\t{c}\n")
        f_crit.write("\n")
        f_full.flush(); f_cond.flush(); f_crit.flush()
        print(f"[{idx+1}/{len(records)}] pred={pred} gold={rec['label']}")
        time.sleep(args.sleep)

    if f_full: f_full.close()
    if f_cond: f_cond.close()
    if f_crit: f_crit.close()
    print(f"\nV2 feito em {time.time()-t0:.1f}s - {total_tokens} tokens - outputs em {outdir}/")


if __name__ == "__main__":
    main()
