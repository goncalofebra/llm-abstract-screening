"""
prep/make_criteria.py
Constroi o ficheiro de criterios de inclusao/exclusao a partir de listas
passadas via CLI ou ficheiros (1 criterio por linha).

Uso 1 (CLI args):
    python prep/make_criteria.py \\
        --tag RV4 \\
        --citation "Costa 2026 (PMID xxx)" \\
        --inclusion "Questionnaires aimed at health professionals" \\
                    "Free Full Text" \\
                    "Written in English" \\
                    "Published in the last 10 years" \\
        --exclusion "Articles that don't match the inclusion criteria" \\
                    "Articles out of context" \\
                    "Articles with high risk of bias" \\
        --output prompts/criteria_RV4.txt

Uso 2 (ficheiros — 1 criterio por linha; comentarios com '#' ignorados):
    python prep/make_criteria.py \\
        --tag RV4 \\
        --citation "Costa 2026" \\
        --inclusion-file inclusion.txt \\
        --exclusion-file exclusion.txt \\
        --output prompts/criteria_RV4.txt
"""

import argparse
from pathlib import Path


def _read_list_file(path: str) -> list:
    """Le um ficheiro com 1 item por linha, ignora linhas em branco e comentarios."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _format_section(title: str, items: list) -> str:
    if not items:
        return f"{title}:\n(none)\n"
    body = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))
    return f"{title}:\n{body}\n"


def parse_args():
    p = argparse.ArgumentParser(
        prog="make_criteria",
        description="Build an eligibility criteria txt for the screener.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tag", required=True,
                   help='SR tag for the header comment, eg. "RV3" or "RV4".')
    p.add_argument("--citation", default="",
                   help='Optional citation header, eg. "Giansanti 2022 (PMID 36033812)".')
    p.add_argument("--inclusion", nargs="+", default=[],
                   help="Inclusion criteria as space-separated args (quote each).")
    p.add_argument("--inclusion-file", default="",
                   help="Alternative: file with 1 inclusion criterion per line.")
    p.add_argument("--exclusion", nargs="+", default=[],
                   help="Exclusion criteria as space-separated args (quote each).")
    p.add_argument("--exclusion-file", default="",
                   help="Alternative: file with 1 exclusion criterion per line.")
    p.add_argument("--output", required=True, help="Output path for the criteria txt.")
    p.add_argument("--print", action="store_true", help="Echo to stdout after writing.")
    return p.parse_args()


def main():
    args = parse_args()
    inclusion = args.inclusion or (_read_list_file(args.inclusion_file) if args.inclusion_file else [])
    exclusion = args.exclusion or (_read_list_file(args.exclusion_file) if args.exclusion_file else [])

    if not inclusion and not exclusion:
        raise SystemExit("[erro] tens de passar --inclusion/--inclusion-file ou --exclusion/--exclusion-file (pelo menos um).")

    parts = [f"# {args.tag} criteria"]
    if args.citation:
        parts.append(f"# {args.citation}")
    parts.append("")
    parts.append(_format_section("Inclusion criteria", inclusion))
    parts.append(_format_section("Exclusion criteria", exclusion))
    text = "\n".join(parts).rstrip() + "\n"

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"-> {out}  ({len(inclusion)} inclusion + {len(exclusion)} exclusion criteria)")
    if args.print:
        print()
        print(text)


if __name__ == "__main__":
    main()
