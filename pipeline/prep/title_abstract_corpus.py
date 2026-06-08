"""
prep/title_abstract_corpus.py
Converte um xlsx (formato Citations Export estilo Litmaps) para:
  - AbstractTexts/<tag>.txt no formato Title:/Abstract:/Label Included:
  - data/<tag>/metadata.csv com title, abstract, doi, pmid, urls + labels (T&A e final)

Bypassa o bug 'xxid' do openpyxl 3.1.5 parsing o xlsx via zipfile + xml.etree.

Colunas esperadas (case-sensitive):
  title, abstract, doi, source_id (PMID), url,
  is_include_ab  ('Yes'/'No')   -> gold T&A
  is_final_include ('Yes'/'No') -> gold final (vai para Label Included)

Uso:
    python prep/title_abstract_corpus.py \\
        --xlsx data/257879_CitationsExport_20260602055159.xlsx \\
        --tag RV4 \\
        --abstracts-out AbstractTexts/RV4.txt \\
        --metadata-out data/rv4/metadata.csv

A label que vai para 'Label Included:' e is_final_include (n=27 em RV4) para
manter consistencia metodologica com RV3. Para a metrica F1_TA usa
'gold_eval.py metrics --ta-positives N' onde N e o n_ab.
"""

import argparse
import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_letter_to_idx(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1


def _load_xlsx_rows(xlsx_path: Path, sheet_xml: str = "xl/worksheets/sheet1.xml"):
    """Bypass openpyxl bug. Returns list of dict {col_idx: value}."""
    with zipfile.ZipFile(xlsx_path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.parse(z.open("xl/sharedStrings.xml")).getroot().findall("s:si", NS):
                strings.append("".join((t.text or "") for t in si.findall(".//s:t", NS)))
        sheet_tree = ET.parse(z.open(sheet_xml))
        rows = sheet_tree.getroot().findall(".//s:row", NS)

        out = []
        for row in rows:
            cells = {}
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
                    cells[ci] = val
                elif inline is not None:
                    cells[ci] = "".join((t2.text or "") for t2 in inline.findall(".//s:t", NS))
            out.append(cells)
        return out


def parse_args():
    p = argparse.ArgumentParser(
        prog="title_abstract_corpus",
        description="Convert Citations Export xlsx to AbstractTexts/<tag>.txt + metadata.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--xlsx", required=True, help="Path to xlsx file.")
    p.add_argument("--sheet", default="xl/worksheets/sheet1.xml",
                   help="Internal sheet path (default: sheet1).")
    p.add_argument("--tag", required=True, help='SR tag, eg. "RV4".')
    p.add_argument("--abstracts-out", required=True,
                   help='Output path for Title/Abstract/Label Included txt (eg. "AbstractTexts/RV4.txt").')
    p.add_argument("--metadata-out", required=True,
                   help='Output path for full metadata csv (eg. "data/rv4/metadata.csv").')
    p.add_argument("--label-source", choices=["is_final_include", "is_include_ab"],
                   default="is_final_include",
                   help="Which xlsx column to use as 'Label Included' (default: is_final_include).")
    return p.parse_args()


def main():
    args = parse_args()
    rows = _load_xlsx_rows(Path(args.xlsx), args.sheet)
    if len(rows) < 2:
        raise SystemExit("[erro] Sheet vazia.")

    # Map headers
    header = rows[0]
    headers = [header.get(i) for i in range(max(header) + 1)]
    H = {h: i for i, h in enumerate(headers) if h}
    required = ["title", "abstract", args.label_source]
    for r in required:
        if r not in H:
            raise SystemExit(f"[erro] coluna requerida ausente: {r!r}")

    # Optional columns (graceful)
    OPT = ["doi", "source_id", "url", "first_author", "publication", "pub_year",
           "is_include_ab", "is_include_ft", "is_final_include"]

    # Process data rows
    records = []
    counts = {"with_abstract": 0, "label_yes": 0, "label_no": 0, "label_other": 0,
              "ab_yes": 0, "final_yes": 0}
    for row_cells in rows[1:]:
        title = (row_cells.get(H["title"]) or "").strip()
        abstract = (row_cells.get(H["abstract"]) or "").strip()
        if not title:
            continue
        if abstract:
            counts["with_abstract"] += 1

        label_raw = (row_cells.get(H[args.label_source]) or "").strip()
        if label_raw.lower() == "yes":
            label = 1
            counts["label_yes"] += 1
        elif label_raw.lower() == "no":
            label = 0
            counts["label_no"] += 1
        else:
            label = 0  # default: tratar como excluido
            counts["label_other"] += 1

        # Counters for both gold levels (info only)
        if (row_cells.get(H.get("is_include_ab", -1)) or "").strip().lower() == "yes":
            counts["ab_yes"] += 1
        if (row_cells.get(H.get("is_final_include", -1)) or "").strip().lower() == "yes":
            counts["final_yes"] += 1

        rec = {"title": title, "abstract": abstract, "label_included": label}
        for opt in OPT:
            if opt in H:
                rec[opt] = (row_cells.get(H[opt]) or "").strip()
        records.append(rec)

    # Write abstracts txt
    abs_path = Path(args.abstracts_out)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    with abs_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(f"Title: {rec['title']}\n")
            f.write(f"Abstract: {rec['abstract']}\n")
            f.write(f"Label Included: {rec['label_included']}\n\n")

    # Write metadata csv -- usar nomes COMPATIVEIS com screener.py export
    # (pmid, pubmed_url, journal, publication_date, authors)
    meta_path = Path(args.metadata_out)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["title", "abstract", "doi", "pmid", "pubmed_url", "authors",
              "journal", "publication_date", "is_include_ab", "is_include_ft",
              "is_final_include", "label_included"]
    with meta_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for rec in records:
            pmid = rec.get("source_id", "")
            row = {
                "title": rec.get("title", ""),
                "abstract": rec.get("abstract", ""),
                "doi": rec.get("doi", ""),
                "pmid": pmid,
                "pubmed_url": rec.get("url", "") or (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""),
                "authors": rec.get("first_author", ""),
                "journal": rec.get("publication", ""),
                "publication_date": rec.get("pub_year", ""),
                "is_include_ab": rec.get("is_include_ab", ""),
                "is_include_ft": rec.get("is_include_ft", ""),
                "is_final_include": rec.get("is_final_include", ""),
                "label_included": rec.get("label_included", ""),
            }
            w.writerow(row)

    print(f"-> {abs_path}  ({len(records)} records)")
    print(f"-> {meta_path}")
    print(f"   {counts['with_abstract']} com abstract nao-vazio")
    print(f"   Label fonte: {args.label_source!r} - Yes={counts['label_yes']}, No={counts['label_no']}, outros={counts['label_other']}")
    print(f"   (info) is_include_ab=Yes total: {counts['ab_yes']}  -> usar como --ta-positives no gold_eval")
    print(f"   (info) is_final_include=Yes total: {counts['final_yes']}")


if __name__ == "__main__":
    main()
