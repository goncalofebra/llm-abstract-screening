"""
gold_eval.py
Ferramentas de avaliacao: marcar gold standard + calcular metricas.

Comandos:
    label    - Marca abstracts incluidos pela revisao original como Label Included: 1
    metrics  - Calcula sensibilidade, especificidade, NPV, F1, kappa Cohen, etc.

Exemplos:
    python gold_eval.py label --input AbstractTexts/RV3.txt --output AbstractTexts/RV3.txt
    python gold_eval.py metrics --condensed out/RV3_condensed.txt --tag RV3
"""

import argparse
import csv
import re
from difflib import SequenceMatcher
from pathlib import Path


# ====================================================================
# Comum
# ====================================================================

RECORD_RE = re.compile(
    r"Title:\s*(?P<title>.*?)\n"
    r"Abstract:\s*(?P<abstract>.*?)\n"
    r"Label Included:\s*(?P<label>[01])",
    flags=re.DOTALL,
)


def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ====================================================================
# Sub-comando: label
# ====================================================================

# Default: 34 estudos incluídos em Giansanti 2022 (refs 7-40).
# Para outras SRs, usa --titles-file com 1 título por linha.
DEFAULT_INCLUDED_TITLES = [
    "Evaluation of the National Health Service (NHS) direct pilot telehealth program: cost-effectiveness analysis",
    "A digital behavioral weight gain prevention intervention in primary care practice: cost and cost-effectiveness analysis",
    "Comprehensive management of obstructive sleep apnea by telemedicine: clinical improvement and cost-effectiveness of a virtual sleep unit. A randomized controlled trial",
    "Cost-effectiveness of shared telemedicine appointments in young adults with T1D: CoYoT1 trial",
    "Cost-effectiveness of a mobile-phone text messaging intervention on type 2 diabetes - a randomized-controlled trial",
    "Mobile health coaching on nutrition and lifestyle behaviors for subfertile couples using the smarter pregnancy program: model-based cost-effectiveness analysis",
    "Effectiveness of mobile application for menstrual management of working women in Japan: randomized controlled trial and medical economic evaluation",
    "Long-term outcomes and cost-effectiveness of breast cancer screening with digital breast tomosynthesis in the United States",
    "Drones and digital adherence monitoring for community-based tuberculosis control in remote Madagascar: a cost-effectiveness analysis",
    "Comparison of telemedicine with in-person care for follow-up after elective neurosurgery: results of a cost-effectiveness analysis of 1200 patients using patient-perceived utility scores",
    "Cost-effectiveness of Access to Critical Cerebral Emergency Support Services (ACCESS): a neuro-emergent telemedicine consultation program",
    "Cost-effectiveness of a National Telemedicine Diabetic Retinopathy Screening Program in Singapore",
    "Is telehealthcare for heart failure patients cost-effective? An economic evaluation alongside the Danish TeleCare North heart failure trial",
    "Cost-effectiveness analysis for a tele-based health coaching program for chronic disease in primary care",
    "Cost-effectiveness of a health system-based smoking cessation program",
    "Mobile and traditional cognitive behavioral therapy programs for generalized anxiety disorder: a cost-effectiveness analysis",
    "Costs and cost-effectiveness analyses of mCARE strategies for promoting care seeking of maternal and newborn health services in rural Bangladesh",
    "Health benefits and cost-effectiveness from promoting smartphone apps for weight loss: multistate life table modeling",
    "Cost effectiveness of mHealth intervention by community health workers for reducing maternal and newborn mortality in rural Uttar Pradesh, India",
    "Cost-effectiveness of a mobile health-supported lifestyle intervention for pregnant women with an elevated body mass index",
    "Estimating the impact of novel digital therapeutics in type 2 diabetes and hypertension: health economic analysis",
    "Cost-effectiveness of telemedicine-based collaborative care for posttraumatic stress disorder",
    "Cost-effectiveness of telemedicine-directed specialized vs standard care for patients with inflammatory bowel diseases in a randomized trial",
    "Telemonitoring of Crohn's Disease and Ulcerative colitis (TECCU): cost-effectiveness analysis",
    "Telerehabilitation after total knee replacement in Italy: cost-effectiveness and cost-utility analysis of a mixed telerehabilitation-standard rehabilitation programme compared with usual care",
    "Cost-effectiveness of internet-based cognitive-behavioral treatment for bulimia nervosa: results of a randomized controlled trial",
    "Economic evaluation of telemedicine for patients in ICUs",
    "Cost-effectiveness of telehealthcare to patients with chronic obstructive pulmonary disease: results from the Danish TeleCare North cluster-randomised trial",
    "Economic evaluation of a guided and unguided internet-based CBT intervention for major depression: results from a multicenter, three-armed randomized controlled trial conducted in primary care",
    "Assessment of utilization and cost-effectiveness of telemedicine program in western regions of China: a 12-year study of 249 hospitals across 112 cities",
    "Cost-utility analysis of telemonitoring versus conventional hospital-based follow-up of patients with pacemakers. The NORDLAND randomized clinical trial",
    "Mobile app for treatment of stress urinary incontinence: a cost-effectiveness analysis",
    "Costing and cost-effectiveness of a mobile health intervention (ImTeCHO) in improving infant mortality in tribal areas of Gujarat, India: cluster randomized controlled trial",
    "Cost-effectiveness of a clinical childhood obesity intervention",
]


def cmd_label(args):
    if args.titles_file:
        titles = [
            line.strip() for line in Path(args.titles_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        source = args.titles_file
    else:
        titles = DEFAULT_INCLUDED_TITLES
        source = "default (RV3, Giansanti 2022 refs 7-40)"
    print(f"Títulos gold: {len(titles)} ({source})")

    text = Path(args.input).read_text(encoding="utf-8")
    records = []
    for m in RECORD_RE.finditer(text):
        records.append({
            "match": m,
            "title": m.group("title").strip(),
            "title_norm": normalize(m.group("title")),
            "label_span": m.span("label"),
        })
    print(f"Total records: {len(records)}")

    included_norm = [(t, normalize(t)) for t in titles]
    matches = {}
    found_indices = set()
    for inc_idx, (_, norm) in enumerate(included_norm):
        best_idx, best_ratio = None, 0.0
        for rec_idx, rec in enumerate(records):
            r = SequenceMatcher(None, norm, rec["title_norm"]).ratio()
            if norm in rec["title_norm"] or rec["title_norm"] in norm:
                r = max(r, 0.92)
            if r > best_ratio:
                best_ratio = r
                best_idx = rec_idx
        if best_ratio >= args.threshold and best_idx not in found_indices:
            matches[inc_idx] = (best_idx, best_ratio)
            found_indices.add(best_idx)
        else:
            matches[inc_idx] = (None, best_ratio)

    matched = sum(1 for v in matches.values() if v[0] is not None)
    print(f"Matched: {matched}/{len(titles)}\n")
    print("=== Matched ===")
    for inc_idx, (rec_idx, ratio) in sorted(matches.items()):
        if rec_idx is not None:
            print(f"[{inc_idx+1:>2}] ratio={ratio:.2f}")
            print(f"     expected: {titles[inc_idx][:100]}")
            print(f"     found:    {records[rec_idx]['title'][:100]}")
    print("\n=== NOT matched ===")
    for inc_idx, (rec_idx, ratio) in sorted(matches.items()):
        if rec_idx is None:
            print(f"[{inc_idx+1:>2}] best ratio={ratio:.2f}")
            print(f"     expected: {titles[inc_idx][:100]}")

    parts, last = [], 0
    for rec_idx, rec in enumerate(records):
        new_label = "1" if rec_idx in found_indices else rec["match"].group("label")
        s, e = rec["label_span"]
        parts.append(text[last:s])
        parts.append(new_label)
        last = e
    parts.append(text[last:])
    Path(args.output).write_text("".join(parts), encoding="utf-8")
    print(f"\n-> Wrote {args.output}")
    print(f"   Positives marked: {len(found_indices)}")


# ====================================================================
# Sub-comando: metrics
# ====================================================================

def load_condensed(path: Path):
    y_true, y_pred, dropped = [], [], 0
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            pred = int(row["pred"])
            gold = int(row["gold"])
            if pred not in (0, 1):
                dropped += 1
                continue
            y_pred.append(pred)
            y_true.append(gold)
    return y_true, y_pred, dropped


def cmd_metrics(args):
    from sklearn.metrics import (
        accuracy_score,
        cohen_kappa_score,
        confusion_matrix,
    )

    y_true, y_pred, dropped = load_condensed(Path(args.condensed))
    n = len(y_true)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    tn, fp, fn, tp = int(tn), int(fp), int(fn), int(tp)

    # --- Bloco 1: avaliacao "extraiu todos os incluidos pela SR final" ---
    # Gold = artigos identificados no corpus (full-text-included da SR original).
    gold_pos_final = tp + fn
    recall_final = tp / gold_pos_final if gold_pos_final else float("nan")

    # --- Bloco 2: metricas de screening contra Title/Abstract gold (n = ta_positives) ---
    # Se --ta-positives N fornecido (e.g. 81 em Giansanti 2022), o recall e calculado vs N.
    # Assumption: os TPs conhecidos (vs full-text) sao um subconjunto dos N positivos T&A.
    # Precisao mantem-se = TP / (TP+FP), porque nao assumimos overlap entre os nossos FPs
    # e os (N - TP) positivos T&A desconhecidos. F1 sai naturalmente.
    N = args.ta_positives if args.ta_positives > 0 else gold_pos_final
    sens_ta = tp / N if N else float("nan")
    prec_ta = tp / (tp + fp) if (tp + fp) else float("nan")
    f1_ta = (2 * sens_ta * prec_ta) / (sens_ta + prec_ta) if (sens_ta + prec_ta) else float("nan")

    # --- Metricas globais (corpus inteiro) ---
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    npv = tn / (tn + fn) if (tn + fn) else float("nan")

    metrics = {
        "tag": args.tag,
        "n_corpus": n,
        "dropped_unparseable": dropped,
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,

        # Recall vs SR original (artigos incluidos no full text)
        "recall_vs_final_SR": round(recall_final, 4),
        "gold_positives_final": gold_pos_final,

        # F1 e screening metrics vs T&A screening level (n = N)
        "ta_positives_total": N,
        "sensitivity_TA": round(sens_ta, 4),
        "precision_TA": round(prec_ta, 4),
        "F1_TA": round(f1_ta, 4),

        # Metricas globais (independentes do level)
        "specificity": round(spec, 4),
        "NPV": round(npv, 4),
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "cohen_kappa": round(cohen_kappa_score(y_true, y_pred), 4),
        "workload_reduction": round((tn + fn) / n, 4) if n else float("nan"),
    }

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{args.tag}_metrics.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for k, v in metrics.items():
            line = f"{k}\t{v}"
            print(line)
            f.write(line + "\n")
    print(f"\n-> {out_path}")


# ====================================================================
# CLI
# ====================================================================

def build_parser():
    p = argparse.ArgumentParser(
        prog="gold_eval",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("label", help="Marca abstracts incluídos como Label Included: 1.")
    pl.add_argument("--input", required=True, help="AbstractTexts/<tag>.txt.")
    pl.add_argument("--output", required=True, help="Pode ser igual ao input para sobrescrever.")
    pl.add_argument("--titles-file", default="", help="Ficheiro com 1 título por linha. Default: lista RV3 hardcoded.")
    pl.add_argument("--threshold", type=float, default=0.80, help="Ratio mínimo do fuzzy match (default 0.80).")
    pl.set_defaults(func=cmd_label)

    pm = sub.add_parser("metrics", help="Calcula metricas vs gold standard (full-text e/ou T&A).")
    pm.add_argument("--condensed", required=True, help="out/<tag>_condensed.txt.")
    pm.add_argument("--tag", required=True)
    pm.add_argument("--ta-positives", type=int, default=0,
                    help="N positivos da fase T&A da SR original (e.g. 81 em Giansanti 2022). "
                         "Quando >0, F1/precision/recall sao calculados a este nivel. Default: usa gold do corpus.")
    pm.add_argument("--outdir", default="out")
    pm.set_defaults(func=cmd_metrics)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
