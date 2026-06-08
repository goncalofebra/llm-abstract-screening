"""
Importadores de corpus: .txt (nativo) / .csv / .xlsx (Citations Export).

Devolvem uma lista de dicts normalizados:
    {title, abstract, doi, pmid, journal, authors, publication_date, pubmed_url, gold_label}

O leitor de .xlsx usa zipfile + xml.etree (contorna o bug 'xxid' do openpyxl 3.1.5),
a mesma abordagem do prep/title_abstract_corpus.py que ja validou os ficheiros reais.
"""

from __future__ import annotations

import csv as _csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, Tuple

import screening_core

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# variantes de nome de coluna (lowercase) -> campo canonico
COLUMN_ALIASES = {
    "title": "title",
    "abstract": "abstract",
    "doi": "doi",
    "pmid": "pmid",
    "source_id": "pmid",
    "pubmed_id": "pmid",
    "journal": "journal",
    "publication": "journal",
    "source": "journal",
    "authors": "authors",
    "author": "authors",
    "first_author": "authors",
    "publication_date": "publication_date",
    "pub_year": "publication_date",
    "year": "publication_date",
    "date": "publication_date",
    "pubmed_url": "pubmed_url",
    "url": "pubmed_url",
}

# colunas que servem de gold standard (Yes/No ou 1/0)
GOLD_COLUMNS = ("label_included", "label included", "is_final_include", "gold", "included")


def _to_gold(value: str) -> Optional[int]:
    v = (value or "").strip().lower()
    if v in ("1", "yes", "true", "include", "included"):
        return 1
    if v in ("0", "no", "false", "exclude", "excluded"):
        return 0
    return None


def _rows_to_records(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, object]], List[str]]:
    """rows: lista de dicts header->valor (headers ja em lowercase/strip)."""
    warnings: List[str] = []
    if not rows:
        return [], ["Ficheiro sem linhas de dados."]

    present = set(rows[0].keys())
    if "title" not in present:
        warnings.append("Coluna 'title' nao encontrada - nao foi possivel importar.")
        return [], warnings

    gold_col = next((c for c in GOLD_COLUMNS if c in present), None)

    records: List[Dict[str, object]] = []
    for row in rows:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        rec: Dict[str, object] = {
            "title": title,
            "abstract": (row.get("abstract") or "").strip(),
            "doi": "", "pmid": "", "journal": "", "authors": "",
            "publication_date": "", "pubmed_url": "", "gold_label": None,
        }
        for raw_key, value in row.items():
            field = COLUMN_ALIASES.get(raw_key)
            if field and field not in ("title", "abstract") and value:
                rec[field] = str(value).strip()
        if gold_col is not None:
            rec["gold_label"] = _to_gold(row.get(gold_col, ""))
        if not rec["pubmed_url"] and rec["pmid"]:
            rec["pubmed_url"] = "https://pubmed.ncbi.nlm.nih.gov/{}/".format(rec["pmid"])
        records.append(rec)

    if not records:
        warnings.append("Nenhum registo com 'title' nao-vazio.")
    return records, warnings


def _parse_csv(raw: bytes) -> Tuple[List[Dict[str, object]], List[str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = _csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        rows.append({(k or "").strip().lower(): (v or "") for k, v in row.items()})
    return _rows_to_records(rows)


def _col_letter_to_idx(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1


def _parse_xlsx(raw: bytes) -> Tuple[List[Dict[str, object]], List[str]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        strings: List[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.parse(z.open("xl/sharedStrings.xml")).getroot()
            for si in root.findall("s:si", NS):
                strings.append("".join((t.text or "") for t in si.findall(".//s:t", NS)))
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in names:
            sheet_candidates = [n for n in names if n.startswith("xl/worksheets/") and n.endswith(".xml")]
            if not sheet_candidates:
                return [], ["xlsx sem worksheet legivel."]
            sheet_name = sorted(sheet_candidates)[0]
        sheet_root = ET.parse(z.open(sheet_name)).getroot()

        raw_rows = []
        for row in sheet_root.findall(".//s:row", NS):
            cells: Dict[int, str] = {}
            for c in row.findall("s:c", NS):
                ref = c.get("r", "")
                m = re.match(r"^([A-Z]+)", ref)
                if not m:
                    continue
                ci = _col_letter_to_idx(m.group(1))
                t = c.get("t", "n")
                v = c.find("s:v", NS)
                inline = c.find("s:is", NS)
                if v is not None:
                    val = v.text
                    if t == "s":
                        val = strings[int(val)] if val and val.isdigit() else None
                    cells[ci] = val if val is not None else ""
                elif inline is not None:
                    cells[ci] = "".join((t2.text or "") for t2 in inline.findall(".//s:t", NS))
            raw_rows.append(cells)

    if len(raw_rows) < 2:
        return [], ["xlsx vazio ou so com cabecalho."]

    header_cells = raw_rows[0]
    max_idx = max(header_cells) if header_cells else -1
    headers = [(header_cells.get(i) or "").strip().lower() for i in range(max_idx + 1)]
    rows = []
    for cells in raw_rows[1:]:
        row = {}
        for i, h in enumerate(headers):
            if h:
                row[h] = cells.get(i, "") or ""
        rows.append(row)
    return _rows_to_records(rows)


def parse_upload(filename: str, raw: bytes) -> Tuple[List[Dict[str, object]], List[str]]:
    """Dispatcher por extensao. Devolve (records, warnings)."""
    name = (filename or "").lower()
    if name.endswith(".txt"):
        text = raw.decode("utf-8", errors="replace")
        recs = screening_core.parse_abstract_txt(text)
        # normaliza para o mesmo shape dos outros importadores
        out = []
        for r in recs:
            out.append({
                "title": r.get("title", ""), "abstract": r.get("abstract", ""),
                "doi": "", "pmid": "", "journal": "", "authors": "",
                "publication_date": "", "pubmed_url": "",
                "gold_label": r.get("gold_label"),
            })
        warns = [] if out else ["Nenhum registo no formato Title:/Abstract:/Label Included:."]
        return out, warns
    if name.endswith(".csv"):
        return _parse_csv(raw)
    if name.endswith(".xlsx"):
        return _parse_xlsx(raw)
    return [], ["Extensao nao suportada: usa .txt, .csv ou .xlsx."]
