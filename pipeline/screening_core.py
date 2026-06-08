"""
screening_core.py
Nucleo partilhado da pipeline de Title/Abstract screening.

Fonte unica de verdade para:
  - construcao de prompts V1 (single user message, estilo Li 2024)
    e V2 (system + user, estilo Dennstadt 2024);
  - chamada aos 4 providers (OpenAI / DeepSeek / Groq / Ollama),
    incl. desligar o thinking mode do qwen3 (think:false, Ollama nativo)
    e do DeepSeek (extra_body thinking disabled);
  - parsing das respostas yes/no;
  - extracao PubMed (esearch + efetch).

Compativel com Python 3.9 (sem sintaxe 3.10+; usa Optional/List/Dict).
Os scripts CLI (screener.py, screener_2txt.py, screener_3txt.py) mantem-se
intactos; este modulo e' consumido pelo web app Django e pode, no futuro,
substituir a logica duplicada nesses scripts.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# ====================================================================
# Providers
# ====================================================================

PROVIDERS: Dict[str, Dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-2024-11-20",
        "label": "OpenAI GPT-4o (cloud)",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
        "label": "DeepSeek-V4-Flash (cloud)",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "label": "Groq Llama-3.3-70B (cloud)",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": "OLLAMA_API_KEY",
        "default_model": "qwen3:8b",
        "label": "Ollama qwen3:8B (local)",
    },
}

PROMPT_STRUCTURES = (
    ("V1", "V1 - single user message (Li 2024)"),
    ("V2", "V2 - system + user (Dennstadt 2024)"),
)

OLLAMA_NATIVE_URL = "http://localhost:11434/api/chat"


# ====================================================================
# Configuracao de uma run
# ====================================================================

@dataclass
class ScreenConfig:
    provider: str = "deepseek"
    model: str = ""
    prompt_structure: str = "V2"          # "V1" ou "V2"
    base_prompt: str = ""                  # instrucao generica
    criteria: str = ""                     # criterios I/E
    temperature: float = 0.0
    max_tokens: int = 100
    no_think: bool = True
    api_key: str = ""                      # resolvida pelo chamador (env)

    def resolved_model(self) -> str:
        return self.model or PROVIDERS[self.provider]["default_model"]

    def base_url(self) -> str:
        return PROVIDERS[self.provider]["base_url"]


@dataclass
class ScreenResult:
    pred: int                              # 1 include, 0 exclude, -1 unparseable
    per_criterion: List[int] = field(default_factory=list)
    raw_response: str = ""
    tokens: int = 0


# ====================================================================
# Construcao de prompts
# ====================================================================

def _system_content(base_prompt: str, criteria: str) -> str:
    base = (base_prompt or "").strip()
    crit = (criteria or "").strip()
    if crit:
        return f"{base}\n\nEligibility criteria:\n{crit}"
    return base


def build_messages(
    structure: str,
    base_prompt: str,
    criteria: str,
    title: str,
    abstract: str,
    no_think: bool = False,
    provider: str = "openai",
) -> List[Dict[str, str]]:
    """
    V1: uma unica mensagem user (instrucao + criterios + title + abstract).
    V2: mensagem system (instrucao + criterios) + mensagem user (title + abstract).

    O prefixo textual /no_think (idiossincrasia do qwen3) so e' usado quando
    no_think=True e o provider NAO e' ollama (que usa think:false na API nativa)
    nem deepseek (que usa extra_body). Para esses dois, build_messages nao
    altera o conteudo - o desligar do raciocinio e' feito em call_llm.
    """
    structure = (structure or "V2").upper()
    sys_content = _system_content(base_prompt, criteria)
    user_content = f"Title: {title}\n\nAbstract: {abstract}"
    use_text_no_think = no_think and provider not in ("ollama", "deepseek")

    if structure == "V1":
        # Single user message; sem system.
        combined = f"{sys_content}\n\n{user_content}"
        if use_text_no_think:
            combined = "/no_think\n" + combined
        return [{"role": "user", "content": combined}]

    # V2 (default): system + user.
    sys_msg = sys_content
    if use_text_no_think:
        sys_msg = "/no_think\n" + sys_msg
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_content},
    ]


# ====================================================================
# Parsing das respostas
# ====================================================================

def yes_no_to_binary(token: str) -> Optional[int]:
    t = token.strip().lower().rstrip(".,;:")
    if t == "yes":
        return 1
    if t == "no":
        return 0
    return None


def parse_response(text: str) -> Tuple[Optional[int], List[int]]:
    tokens = [yes_no_to_binary(line) for line in (text or "").splitlines() if line.strip()]
    tokens = [t for t in tokens if t is not None]
    if not tokens:
        return None, []
    return tokens[0], tokens[1:]


# ====================================================================
# Chamada ao LLM
# ====================================================================

def make_client(config: ScreenConfig):
    """Devolve um cliente OpenAI-compativel, ou None para Ollama nativo."""
    if config.provider == "ollama":
        return None
    from openai import OpenAI
    api_key = config.api_key or ("ollama" if config.provider == "ollama" else "")
    return OpenAI(api_key=api_key, base_url=config.base_url())


def call_llm(config: ScreenConfig, messages: List[Dict[str, str]], client=None) -> Tuple[str, int]:
    """Chama o modelo e devolve (conteudo, n_tokens). Pode lancar excecao."""
    model = config.resolved_model()

    if config.provider == "ollama":
        import requests
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": config.temperature, "num_predict": config.max_tokens},
        }
        if config.no_think:
            payload["think"] = False
        r = requests.post(OLLAMA_NATIVE_URL, json=payload, timeout=300)
        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "") or ""
        tokens = (data.get("prompt_eval_count", 0) or 0) + (data.get("eval_count", 0) or 0)
        return content, tokens

    if client is None:
        client = make_client(config)
    extra = {}
    if config.provider == "deepseek" and config.no_think:
        extra["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        top_p=1,
        **extra,
    )
    content = resp.choices[0].message.content or ""
    tokens = getattr(resp.usage, "total_tokens", 0) or 0
    return content, tokens


def screen_one(title: str, abstract: str, config: ScreenConfig, client=None) -> ScreenResult:
    """Screena um unico registo. Lanca excecao se a chamada API falhar."""
    messages = build_messages(
        config.prompt_structure, config.base_prompt, config.criteria,
        title, abstract, no_think=config.no_think, provider=config.provider,
    )
    content, tokens = call_llm(config, messages, client=client)
    overall, per_criterion = parse_response(content)
    pred = overall if overall is not None else -1
    return ScreenResult(pred=pred, per_criterion=per_criterion, raw_response=content, tokens=tokens)


def screen_records(
    records: List[Dict[str, str]],
    config: ScreenConfig,
    on_result: Optional[Callable[[int, Dict[str, str], ScreenResult], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_error: Optional[Callable[[int, Exception], None]] = None,
    sleep: float = 0.0,
) -> int:
    """
    Itera sobre records ({"title","abstract"}), chamando on_result(idx, rec, result)
    por cada um. Verifica should_cancel() entre registos. Devolve nº processados.
    Reutilizavel pela CLI e pelo worker Django.
    """
    client = make_client(config)
    processed = 0
    for idx, rec in enumerate(records):
        if should_cancel is not None and should_cancel():
            break
        try:
            result = screen_one(rec.get("title", ""), rec.get("abstract", ""), config, client=client)
        except Exception as exc:  # noqa: BLE001 - reportado via callback
            if on_error is not None:
                on_error(idx, exc)
            if sleep:
                time.sleep(sleep * 5)
            continue
        if on_result is not None:
            on_result(idx, rec, result)
        processed += 1
        if sleep:
            time.sleep(sleep)
    return processed


# ====================================================================
# Parser do formato nativo Title:/Abstract:/Label Included:
# ====================================================================

RECORD_RE = re.compile(
    r"Title:\s*(?P<title>.*?)\n"
    r"Abstract:\s*(?P<abstract>.*?)\n"
    r"Label Included:\s*(?P<label>[01])",
    flags=re.DOTALL,
)


def parse_abstract_txt(text: str) -> List[Dict[str, object]]:
    """Le o formato nativo Title:/Abstract:/Label Included: -> lista de dicts."""
    out: List[Dict[str, object]] = []
    for m in RECORD_RE.finditer(text):
        out.append({
            "title": m.group("title").strip(),
            "abstract": m.group("abstract").strip(),
            "gold_label": int(m.group("label")),
        })
    return out


# ====================================================================
# Extracao PubMed (adaptado de screener.py extract)
# ====================================================================

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _eutils_get(endpoint: str, params: Dict[str, object], retries: int = 3) -> bytes:
    url = "{}/{}?{}".format(EUTILS, endpoint, urllib.parse.urlencode(params))
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gic-screening-webapp/1.0"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 + attempt * 2)
    raise RuntimeError("NCBI request failed after {} attempts: {}".format(retries, last_error))


def pubmed_search(
    query: str,
    from_year: int = 0,
    to_year: int = 0,
    datetype: str = "pdat",
    api_key: str = "",
    email: str = "",
    tool: str = "gic-screening-webapp",
) -> Tuple[str, str, int]:
    params: Dict[str, object] = {
        "db": "pubmed", "term": query, "usehistory": "y",
        "retmode": "json", "retmax": 0, "tool": tool,
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    if from_year or to_year:
        params["datetype"] = datetype
        if from_year:
            params["mindate"] = "{}/01/01".format(from_year)
        if to_year:
            params["maxdate"] = "{}/12/31".format(to_year)
    payload = json.loads(_eutils_get("esearch.fcgi", params).decode("utf-8"))
    result = payload["esearchresult"]
    return result["webenv"], result["querykey"], int(result["count"])


def _pubmed_efetch(webenv: str, query_key: str, start: int, count: int,
                   api_key: str = "", email: str = "", tool: str = "gic-screening-webapp") -> ET.Element:
    params: Dict[str, object] = {
        "db": "pubmed", "query_key": query_key, "WebEnv": webenv,
        "retstart": start, "retmax": count, "retmode": "xml", "tool": tool,
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    return ET.fromstring(_eutils_get("efetch.fcgi", params))


def _text_of(node: Optional[ET.Element]) -> str:
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
        parts.append("{}: {}".format(label, text) if label else text)
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


def _article_to_record(pubmed_article: ET.Element) -> Dict[str, str]:
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
        "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/{}/".format(pmid) if pmid else "",
    }


def pubmed_extract(
    query: str,
    max_results: int = 1000,
    batch_size: int = 200,
    from_year: int = 0,
    to_year: int = 0,
    datetype: str = "pdat",
    api_key: str = "",
    email: str = "",
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, str]]:
    """
    Corre uma query PubMed e devolve registos (com title/abstract/metadados).
    on_progress(descarregados, total) chamado por batch; should_cancel() entre batches.
    """
    webenv, query_key, total_count = pubmed_search(
        query, from_year=from_year, to_year=to_year, datetype=datetype,
        api_key=api_key, email=email,
    )
    limit = min(max_results, total_count)
    records: List[Dict[str, str]] = []
    for start in range(0, limit, batch_size):
        if should_cancel is not None and should_cancel():
            break
        batch_count = min(batch_size, limit - start)
        root = _pubmed_efetch(webenv, query_key, start, batch_count, api_key=api_key, email=email)
        for pa in root.findall("PubmedArticle"):
            rec = _article_to_record(pa)
            if rec and rec.get("title"):
                records.append(rec)
        if on_progress is not None:
            on_progress(len(records), limit)
        time.sleep(0.11 if api_key else 0.34)
    return records
