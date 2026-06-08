"""
prep/make_system.py
Concatena baseprompt + criteria num unico ficheiro system_RV*.txt
para uso com screener_2txt.py (modo V2: system+user).

Estrutura final:
    [conteudo do baseprompt]
    <linha em branco>
    Eligibility criteria:
    [conteudo do criteria, sem comentarios '#']

Uso:
    python prep/make_system.py \\
        --baseprompt prompts/baseprompt_RV4.txt \\
        --criteria prompts/criteria_RV4.txt \\
        --output prompts/system_RV4.txt
"""

import argparse
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(
        prog="make_system",
        description="Concatenate baseprompt + criteria into a single system_*.txt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--baseprompt", required=True, help="Path to baseprompt txt (input).")
    p.add_argument("--criteria", required=True, help="Path to criteria txt (input).")
    p.add_argument("--output", required=True, help="Output path for system txt.")
    p.add_argument("--strip-comments", action="store_true", default=True,
                   help="Strip lines starting with '#' from criteria (default: yes).")
    return p.parse_args()


def main():
    args = parse_args()
    base = Path(args.baseprompt).read_text(encoding="utf-8").strip()
    crit_raw = Path(args.criteria).read_text(encoding="utf-8").splitlines()
    if args.strip_comments:
        crit_raw = [ln for ln in crit_raw if not ln.strip().startswith("#")]
    crit = "\n".join(crit_raw).strip()

    text = f"{base}\n\nEligibility criteria:\n{crit}\n"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"-> {out}  ({len(text)} chars)")


if __name__ == "__main__":
    main()
