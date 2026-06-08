"""
prep/make_baseprompt.py
Constroi o baseprompt.txt (instrucao generica para o LLM) a partir de
parametros da SR: titulo, citacao, scope/topico, e formato de output.

Uso (CLI args):
    python prep/make_baseprompt.py \\
        --sr-title "Cost-effectiveness of digital health interventions" \\
        --sr-citation "Giansanti 2022" \\
        --scope "telemedicine, telehealth, mHealth, wearables, remote monitoring, digital therapeutics" \\
        --analysis-types "cost-effectiveness, cost-utility, cost-benefit, cost-minimization" \\
        --output prompts/baseprompt_RV3.txt

Para passar o scope/analysis-types como uma lista de bullets, separa por '|':
    --scope "A|B|C"  -> "A, B, C" na frase
"""

import argparse
from pathlib import Path
from textwrap import dedent


TEMPLATE = dedent("""\
You are screening articles for a systematic review titled "{sr_title}" ({sr_citation}).

The review aims to identify peer-reviewed studies that {scope_sentence}. Eligible studies report {analysis_types_sentence}.

For each article you will receive the title and the abstract. Decide whether it should be included in the review according to the eligibility criteria provided.

Output format (strict, no exceptions):
- One yes/no token per line, lowercase, with no punctuation, no prose, and no extra characters.
- Line 1: the overall inclusion decision (yes = include, no = exclude).
- Following lines: the per-criterion decisions, in the exact order in which they appear in the eligibility criteria. For each criterion answer:
    yes  if the criterion is satisfied (i.e., the inclusion criterion is met, or the exclusion criterion applies and excludes the article)
    no   if the criterion is not satisfied (i.e., the inclusion criterion is not met, or the exclusion criterion does not apply)

Do not produce any other output. Do not justify your answers. Do not include the criterion text. Only yes/no tokens, one per line.
""")


def _to_sentence(items_pipe_separated: str) -> str:
    """'A|B|C' -> 'A, B, or C'. Plain string -> returned as-is."""
    if "|" not in items_pipe_separated:
        return items_pipe_separated.strip()
    items = [s.strip() for s in items_pipe_separated.split("|") if s.strip()]
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def parse_args():
    p = argparse.ArgumentParser(
        prog="make_baseprompt",
        description="Build a baseprompt.txt from SR parameters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sr-title", required=True,
                   help='Title of the systematic review, eg. "Cost-effectiveness of digital health interventions"')
    p.add_argument("--sr-citation", required=True,
                   help='Short citation, eg. "Giansanti 2022" or "PMID 36033812"')
    p.add_argument("--scope", required=True,
                   help='Scope description. Pipe-separated for a list, eg. "assess A|evaluate B|measure C". '
                        'Becomes "studies that <scope>". Use full sentence if not pipe-separated.')
    p.add_argument("--analysis-types", default="quantitative outcomes relevant to the review",
                   help='Types of analysis. Pipe-separated for a list.')
    p.add_argument("--output", required=True, help="Output path for the baseprompt txt.")
    p.add_argument("--print", action="store_true", help="Echo the prompt to stdout after writing.")
    return p.parse_args()


def main():
    args = parse_args()
    text = TEMPLATE.format(
        sr_title=args.sr_title,
        sr_citation=args.sr_citation,
        scope_sentence=_to_sentence(args.scope),
        analysis_types_sentence=_to_sentence(args.analysis_types),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"-> {out}  ({len(text)} chars, {text.count(chr(10))} lines)")
    if args.print:
        print()
        print(text)


if __name__ == "__main__":
    main()
