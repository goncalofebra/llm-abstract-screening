"""
screener.py
Pipeline completa: extracao PubMed + screening LLM + export com DOI.

Comandos:
    extract  - Descarrega artigos do PubMed (CSV + JSONL + abstracts.txt)
    screen   - Corre LLM sobre abstracts.txt (OpenAI / Groq / Ollama local)
    export   - Cruza condensed.txt com metadata PubMed -> CSV/Excel com DOI dos selecionados

Exemplos:
    python screener.py extract --out pubmed.csv --abstract-txt AbstractTexts/RV3.txt --from-year 2016 --to-year 2020
    python screener.py screen --input AbstractTexts/RV3.txt --criteria eligibilitycriteria_SR.txt --tag RV3
    python screener.py screen --input AbstractTexts/RV3.txt --criteria eligibilitycriteria_SR.txt --tag RV3_qwen3 \\
                              --provider ollama --model qwen3:8b --no-think --sleep 0 --max-tokens 100
    python screener.py export --metadata ../pubmed.csv --abstracts AbstractTexts/RV3.txt \\
                              --condensed out/RV3_condensed.txt --tag RV3
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


# ====================================================================
# Sub-comando: extract  (do pubmed_extract.py)
# ====================================================================

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

DEFAULT_QUERY = (
    '("digital health"[Mesh Terms] OR "digital health" OR '
    '"telemedicine"[Mesh Terms] OR "telemedicine" OR '
    '"e health"[Mesh Terms] OR "e health" OR "electronic health" OR '
    '"m health"[Mesh Terms] OR "m health" OR "mobile health" OR '
    '"remote consultation" OR "digital transformation" OR '
    '"home care services" OR "telenursing" OR '
    '"health innovation"[Mesh Terms] OR "telemetry"[Mesh Terms] OR '
    '"telehealth"[Mesh Terms] OR "telehealth" OR "telecare" OR '
    '"digital care"[Mesh Terms]) AND '
    '("cost analysis"[Mesh Terms] OR "cost analysis" OR '
    '"cost benefit"[Mesh Terms] OR "cost benefit" OR '
    '"cost efficacy"[All Fields] OR "cost effectiveness"[All Fields] OR '
    '"cost consequence"[All Fields] OR "economic evaluation" OR '
    '"economic outcome" OR "economic assessment" OR "hta")'
)


def eutils_get(endpoint: str, params: dict[str, str | int], retries: int = 3) -> bytes:
    url = f"{EUTILS}/{endpoint}?" + urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gic-pubmed-extractor/1.0"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"NCBI request failed after {retries} attempts: {last_error}") from last_error


def esearch(args: argparse.Namespace) -> tuple[str, str, int]:
    params: dict[str, str | int] = {
        "db": "pubmed", "term": args.query, "usehistory": "y",
        "retmode": "json", "retmax": 0, "tool": args.tool,
    }
    if args.api_key:
        params["api_key"] = args.api_key
    if args.email:
        params["email"] = args.email
    if args.from_year or args.to_year:
        params["datetype"] = args.datetype
        if args.from_year:
            params["mindate"] = f"{args.from_year}/01/01"
        if args.to_year:
            params["maxdate"] = f"{args.to_year}/12/31"
    payload = json.loads(eutils_get("esearch.fcgi", params).decode("utf-8"))
    result = payload["esearchresult"]
    return result["webenv"], result["querykey"], int(result["count"])


def efetch(args: argparse.Namespace, webenv: str, query_key: str, start: int, count: int) -> ET.Element:
    params: dict[str, str | int] = {
        "db": "pubmed", "query_key": query_key, "WebEnv": webenv,
        "retstart": start, "retmax": count, "retmode": "xml", "tool": args.tool,
    }
    if args.api_key:
        params["api_key"] = args.api_key
    if args.email:
        params["email"] = args.email
    return ET.fromstring(eutils_get("efetch.fcgi", params))


def _text_of(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _find_text(article: ET.Element, path: str) -> str:
    return _text_of(article.find(path))


def _collect_abstract(article: ET.Element) -> str:
    parts = []
    for abstract_text in article.findall(".//Abstract/AbstractText"):
        label = abstract_text.attrib.get("Label", "").strip()
        text = _text_of(abstract_text)
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return "\n".join(parts)


def _collect_authors(article: ET.Element) -> str:
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _find_text(author, "CollectiveName")
        if collective:
            authors.append(collective)
            continue
        last_name = _find_text(author, "LastName")
        initials = _find_text(author, "Initials")
        name = " ".join(part for part in [last_name, initials] if part)
        if name:
            authors.append(name)
    return "; ".join(authors)


def _collect_mesh_terms(article: ET.Element) -> str:
    terms = []
    for descriptor in article.findall(".//MeshHeading/DescriptorName"):
        term = _text_of(descriptor)
        if term:
            terms.append(term)
    return "; ".join(terms)


def _collect_publication_types(article: ET.Element) -> str:
    return "; ".join(
        _text_of(pub_type)
        for pub_type in article.findall(".//PublicationTypeList/PublicationType")
        if _text_of(pub_type)
    )


def _collect_keywords(article: ET.Element) -> str:
    return "; ".join(
        _text_of(keyword)
        for keyword in article.findall(".//KeywordList/Keyword")
        if _text_of(keyword)
    )


def _collect_publication_date(article: ET.Element) -> str:
    date_node = article.find(".//Journal/JournalIssue/PubDate")
    if date_node is None:
        date_node = article.find(".//PubDate")
    if date_node is None:
        return ""
    year = _find_text(date_node, "Year")
    month = _find_text(date_node, "Month")
    day = _find_text(date_node, "Day")
    medline_date = _find_text(date_node, "MedlineDate")
    if year:
        return "-".join(part for part in [year, month, day] if part)
    return medline_date


def _article_to_record(pubmed_article: ET.Element) -> dict[str, str]:
    medline = pubmed_article.find("MedlineCitation")
    article = medline.find("Article") if medline is not None else None
    if medline is None or article is None:
        return {}
    pmid = _find_text(medline, "PMID")
    title = _find_text(article, "ArticleTitle")
    journal = _find_text(article, "Journal/Title")
    doi = ""
    pmcid = ""
    for article_id in pubmed_article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        id_type = article_id.attrib.get("IdType", "")
        value = _text_of(article_id)
        if id_type == "doi":
            doi = value
        elif id_type == "pmc":
            pmcid = value
    return {
        "pmid": pmid, "title": title, "abstract": _collect_abstract(article),
        "authors": _collect_authors(article), "journal": journal,
        "publication_date": _collect_publication_date(article),
        "doi": doi, "pmcid": pmcid,
        "publication_types": _collect_publication_types(article),
        "mesh_terms": _collect_mesh_terms(article),
        "keywords": _collect_keywords(article),
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    }


def _book_article_to_record(pubmed_book_article: ET.Element) -> dict[str, str]:
    book_doc = pubmed_book_article.find("BookDocument")
    if book_doc is None:
        return {}
    pmid = _find_text(book_doc, "PMID")
    title = _find_text(book_doc, "ArticleTitle") or _find_text(book_doc, "Book/BookTitle")
    book_title = _find_text(book_doc, "Book/BookTitle")
    doi = ""
    pmcid = ""
    for article_id in pubmed_book_article.findall(".//ArticleIdList/ArticleId"):
        id_type = article_id.attrib.get("IdType", "")
        value = _text_of(article_id)
        if id_type == "doi":
            doi = value
        elif id_type == "pmc":
            pmcid = value
    return {
        "pmid": pmid, "title": title, "abstract": _collect_abstract(book_doc),
        "authors": _collect_authors(book_doc), "journal": book_title,
        "publication_date": _collect_publication_date(book_doc),
        "doi": doi, "pmcid": pmcid,
        "publication_types": _collect_publication_types(book_doc),
        "mesh_terms": _collect_mesh_terms(book_doc),
        "keywords": _collect_keywords(book_doc),
        "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    }


def _write_csv(path: Path, records: list[dict[str, str]]) -> None:
    fields = ["pmid", "title", "abstract", "authors", "journal", "publication_date",
              "doi", "pmcid", "publication_types", "mesh_terms", "keywords", "pubmed_url"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def _write_jsonl(path: Path, records: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_abstract_txt(path: Path, records: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(f"Title: {record['title']}\n")
            handle.write(f"Abstract: {record['abstract']}\n")
            handle.write("Label Included: 0\n\n")


def cmd_extract(args):
    if args.batch_size < 1:
        print("[erro] --batch-size tem de ser >= 1", file=sys.stderr)
        return 2
    if args.from_year and args.to_year and args.from_year > args.to_year:
        print("[erro] --from-year não pode ser maior do que --to-year", file=sys.stderr)
        return 2

    webenv, query_key, total_count = esearch(args)
    if args.from_year or args.to_year:
        print(f"Filtro publicação: {args.from_year or 'início'} a {args.to_year or 'fim'} ({args.datetype}).")
    limit = min(args.max_results, total_count)
    print(f"PubMed encontrou {total_count} artigos. A descarregar {limit}.")

    records: list[dict[str, str]] = []
    for start in range(0, limit, args.batch_size):
        batch_count = min(args.batch_size, limit - start)
        root = efetch(args, webenv, query_key, start, batch_count)
        for pa in root.findall("PubmedArticle"):
            rec = _article_to_record(pa)
            if rec:
                records.append(rec)
        for pba in root.findall("PubmedBookArticle"):
            rec = _book_article_to_record(pba)
            if rec:
                records.append(rec)
        print(f"Descarregados {len(records)}/{limit}")
        time.sleep(0.11 if args.api_key else 0.34)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(out_path, records)
    print(f"CSV: {out_path}")
    if args.jsonl:
        _write_jsonl(Path(args.jsonl), records)
        print(f"JSONL: {args.jsonl}")
    if args.abstract_txt:
        _write_abstract_txt(Path(args.abstract_txt), records)
        print(f"TXT abstracts: {args.abstract_txt}")
    return 0


# ====================================================================
# Sub-comando: screen  (do gpt_screener.py)
# ====================================================================

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

# Formato Li 2024: Title:/Abstract:/Label Included:.
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
        sys.exit(f"[erro] Nenhum registo encontrado em {path}. Verifica o formato Title/Abstract/Label Included.")
    return records


def yes_no_to_binary(token: str) -> Optional[int]:
    t = token.strip().lower().rstrip(".,;:")
    if t == "yes":
        return 1
    if t == "no":
        return 0
    return None


def parse_response(response_text: str):
    tokens = [yes_no_to_binary(line) for line in response_text.splitlines() if line.strip()]
    tokens = [t for t in tokens if t is not None]
    if not tokens:
        return None, []
    return tokens[0], tokens[1:]


def cmd_screen(args):
    import requests
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    prov = PROVIDERS[args.provider]
    api_key = os.getenv(prov["key_env"])
    if not api_key:
        if args.provider == "ollama":
            api_key = "ollama"
        else:
            sys.exit(f"[erro] {prov['key_env']} não definida no .env (provider={args.provider}).")
    model = args.model or prov["default_model"]
    print(f"[info] provider={args.provider} model={model} base_url={prov['base_url']}")

    # System message: instrucao + criterios (fixo para todos os abstracts).
    if args.system:
        system_content = Path(args.system).read_text(encoding="utf-8").strip()
        print(f"[info] system={args.system}")
    else:
        if not args.criteria:
            sys.exit("[erro] tens de passar --system <file> ou --criteria <file> (com --base).")
        base_prompt = Path(args.base).read_text(encoding="utf-8").strip()
        criteria = Path(args.criteria).read_text(encoding="utf-8").strip()
        system_content = f"{base_prompt}\n\nEligibility criteria:\n{criteria}"
    records = load_records(Path(args.input))
    if args.limit > 0:
        records = records[: args.limit]

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    # Ficheiros so sao abertos quando vamos mesmo escrever - evita truncar em --dry-run.
    f_full = f_cond = f_crit = None

    use_ollama_native = args.provider == "ollama"
    is_deepseek = args.provider == "deepseek"
    client = None if use_ollama_native else OpenAI(api_key=api_key, base_url=prov["base_url"])
    total_tokens = 0
    t0 = time.time()

    for idx, rec in enumerate(records):
        if idx < args.start:
            continue
        # User message: titulo + abstract do registo atual.
        user_content = f"Title: {rec['title']}\n\nAbstract: {rec['abstract']}"
        if idx == args.start:
            example_path = outdir / f"{args.tag}_prompt_example.txt"
            example_path.write_text(
                f"========== MESSAGE 1: SYSTEM ==========\n{system_content}\n\n"
                f"========== MESSAGE 2: USER ==========\n{user_content}\n",
                encoding="utf-8",
            )
            if args.dry_run:
                print(f"[dry-run] Prompt example -> {example_path}")
                return
            # Primeira iteracao real: abrir os 3 ficheiros de output.
            mode = "a" if args.start > 0 else "w"
            f_full = (outdir / f"{args.tag}_full.txt").open(mode, encoding="utf-8")
            f_cond = (outdir / f"{args.tag}_condensed.txt").open(mode, encoding="utf-8")
            f_crit = (outdir / f"{args.tag}_criteria.txt").open(mode, encoding="utf-8")
            if args.start == 0:
                f_cond.write("idx\tpred\tgold\n")
        # /no_think via system para qwen3/groq (Ollama nativo usa think:false; deepseek usa extra_body).
        sys_msg = system_content
        if args.no_think and not use_ollama_native and not is_deepseek:
            sys_msg = "/no_think\n" + sys_msg
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_content},
        ]
        try:
            if use_ollama_native:
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
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
                    model=model,
                    messages=messages,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    top_p=1,
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
    print(f"\nFeito em {time.time()-t0:.1f}s - {total_tokens} tokens - outputs em {outdir}/")


# ====================================================================
# Sub-comando: export  (do export_selected.py)
# ====================================================================

def _normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _load_records_with_gold(path: Path):
    text = path.read_text(encoding="utf-8")
    out = []
    for m in RECORD_RE.finditer(text):
        out.append({
            "title": m.group("title").strip(),
            "abstract": m.group("abstract").strip(),
            "gold": int(m.group("label")),
        })
    return out


def cmd_export(args):
    import pandas as pd

    records = _load_records_with_gold(Path(args.abstracts))
    print(f"Records em {args.abstracts}: {len(records)}")

    cond = pd.read_csv(args.condensed, sep="\t", dtype={"idx": int, "pred": int, "gold": int})
    selected_idx = cond[cond["pred"] == 1]["idx"].tolist()
    print(f"Selecionados pelo modelo (pred=1): {len(selected_idx)}")

    meta = pd.read_csv(args.metadata, dtype=str).fillna("")
    meta["_norm_title"] = meta["title"].map(_normalize)
    print(f"Records em metadata CSV: {len(meta)}")

    rows = []
    matched = 0
    for idx in selected_idx:
        if idx >= len(records):
            print(f"[aviso] idx={idx} fora do range de records")
            continue
        rec = records[idx]
        norm = _normalize(rec["title"])
        match = meta[meta["_norm_title"] == norm]
        if len(match):
            row = match.iloc[0]
            doi, pmid, url = row["doi"], row["pmid"], row["pubmed_url"]
            journal, pubdate, authors = row["journal"], row["publication_date"], row["authors"]
            matched += 1
        else:
            doi = pmid = url = journal = pubdate = authors = ""
        rows.append({
            "idx": idx,
            "title": rec["title"],
            "abstract": rec["abstract"],
            "doi": doi,
            "pmid": pmid,
            "pubmed_url": url,
            "journal": journal,
            "publication_date": pubdate,
            "authors": authors,
            "gold_label": rec["gold"],
        })

    df = pd.DataFrame(rows)
    print(f"Match com metadata: {matched}/{len(rows)}")
    with_doi = (df["doi"].str.strip() != "").sum() if len(df) else 0
    print(f"Com DOI: {with_doi}/{len(df)}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / f"{args.tag}_selected.csv"
    xlsx_path = outdir / f"{args.tag}_selected.xlsx"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(xlsx_path, index=False)
    print(f"-> {csv_path}")
    print(f"-> {xlsx_path}")


# ====================================================================
# CLI
# ====================================================================

def build_parser():
    p = argparse.ArgumentParser(
        prog="screener",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # --- extract ---
    pe = sub.add_parser("extract", help="Descarrega artigos PubMed para CSV/JSONL/TXT.")
    pe.add_argument("--out", default="pubmed_articles.csv", help="CSV output path.")
    pe.add_argument("--jsonl", default="", help="JSONL output path opcional.")
    pe.add_argument("--abstract-txt", default="", help="Path TXT estilo Title/Abstract/Label Included.")
    pe.add_argument("--max-results", type=int, default=1000)
    pe.add_argument("--batch-size", type=int, default=200)
    pe.add_argument("--api-key", default=os.getenv("NCBI_API_KEY", ""), help="NCBI_API_KEY env var.")
    pe.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""), help="NCBI_EMAIL env var.")
    pe.add_argument("--tool", default="gic-pubmed-extractor")
    pe.add_argument("--query", default=DEFAULT_QUERY, help="PubMed query.")
    pe.add_argument("--from-year", type=int, default=0)
    pe.add_argument("--to-year", type=int, default=0)
    pe.add_argument("--datetype", default="pdat")
    pe.set_defaults(func=cmd_extract)

    # --- screen ---
    ps = sub.add_parser("screen", help="Corre LLM screening (OpenAI / Groq / Ollama).")
    ps.add_argument("--input", required=True, help="Ficheiro .txt com abstracts.")
    ps.add_argument("--system", default="", help="Ficheiro unico com instrucao+criterios (alternativa a --base+--criteria).")
    ps.add_argument("--criteria", default="", help="eligibilitycriteria.txt da SR/MA (usado se --system nao for passado).")
    ps.add_argument("--base", default="", help="Instrucao generica (ex: prompts/baseprompt_RV3.txt). Usado com --criteria se nao passares --system.")
    ps.add_argument("--tag", required=True, help="Identificador (ex: RV3, RV3_qwen3).")
    ps.add_argument("--provider", choices=list(PROVIDERS.keys()), default="openai")
    ps.add_argument("--model", default=None, help="Override do modelo (default depende do provider).")
    ps.add_argument("--temperature", type=float, default=0.0)
    ps.add_argument("--max-tokens", type=int, default=4000)
    ps.add_argument("--sleep", type=float, default=1.0)
    ps.add_argument("--outdir", default="out")
    ps.add_argument("--limit", type=int, default=0, help="Só os N primeiros (debug).")
    ps.add_argument("--start", type=int, default=0, help="Idx inicial; append se > 0.")
    ps.add_argument("--no-think", action="store_true", help="Desliga thinking mode (qwen3).")
    ps.add_argument("--dry-run", action="store_true", help="So monta o prompt do 1.o registo em out/<tag>_prompt_example.txt e sai (nao chama LLM).")
    ps.set_defaults(func=cmd_screen)

    # --- export ---
    px = sub.add_parser("export", help="Cruza condensed + metadata -> CSV/Excel dos selecionados.")
    px.add_argument("--metadata", required=True, help="CSV PubMed (com colunas title, doi, pmid, ...).")
    px.add_argument("--abstracts", required=True, help="AbstractTexts/<tag>.txt.")
    px.add_argument("--condensed", required=True, help="out/<tag>_condensed.txt.")
    px.add_argument("--tag", required=True)
    px.add_argument("--outdir", default="out")
    px.set_defaults(func=cmd_export)

    return p


def main():
    args = build_parser().parse_args()
    rc = args.func(args)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
