from __future__ import annotations

import csv
import io

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import worker
from .envfile import MANAGED_KEYS, masked_status, write_env
from .forms import ExtractForm, ProjectForm, RunForm, SettingsForm, UploadForm
from .importers import parse_upload
from .models import EXCLUDE, INCLUDE, UNPARSEABLE, Prediction, Project, ScreeningRun
from .providers_util import available_providers


# ====================================================================
# Projetos
# ====================================================================

def project_list(request):
    projects = Project.objects.all()
    return render(request, "screening/project_list.html", {"projects": projects})


def settings_view(request):
    if request.method == "POST":
        form = SettingsForm(request.POST)
        if form.is_valid():
            write_env({k: form.cleaned_data.get(k, "") for k in MANAGED_KEYS})
            messages.success(request, "Chaves guardadas. Aplicadas de imediato ao screening.")
            return redirect("settings")
    else:
        form = SettingsForm()
    return render(request, "screening/settings.html", {
        "form": form,
        "status": masked_status(),
        "providers": available_providers(),
    })


def project_create(request):
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            messages.success(request, "Projeto criado.")
            return redirect("project_detail", pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, "screening/project_form.html", {"form": form, "creating": True})


def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, "Projeto atualizado.")
            return redirect("project_detail", pk=project.pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, "screening/project_form.html", {"form": form, "project": project, "creating": False})


@require_POST
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    project.delete()
    messages.success(request, "Projeto eliminado.")
    return redirect("project_list")


def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    providers = available_providers()
    provider_choices = [(p["key"], p["label"]) for p in providers if p["available"]]
    run_form = RunForm(
        provider_choices=provider_choices,
        initial={
            "provider": project.provider,
            "model": project.model,
            "prompt_structure": project.prompt_structure,
            "temperature": project.temperature,
            "max_tokens": project.max_tokens,
            "no_think": project.no_think,
        },
    )
    context = {
        "project": project,
        "record_count": project.record_count,
        "runs": project.runs.all(),
        "upload_form": UploadForm(),
        "extract_form": ExtractForm(),
        "run_form": run_form,
        "providers": providers,
        "any_provider": bool(provider_choices),
        "extract_active": worker.extract_status(project.pk).get("status") == "running",
    }
    return render(request, "screening/project_detail.html", context)


# ====================================================================
# Popular records: upload / extract
# ====================================================================

@require_POST
def upload_records(request, pk):
    project = get_object_or_404(Project, pk=pk)
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Upload invalido.")
        return redirect("project_detail", pk=pk)

    upload = form.cleaned_data["file"]
    records, warnings = parse_upload(upload.name, upload.read())
    created = 0
    if records:
        try:
            created = worker.append_records(project, records)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, "Falha a importar: {}".format(exc))
            return redirect("project_detail", pk=pk)

    if created:
        messages.success(request, "Importados {} records de '{}'.".format(created, upload.name))
    for w in warnings:
        messages.warning(request, w)
    return redirect("project_detail", pk=pk)


@require_POST
def records_clear(request, pk):
    project = get_object_or_404(Project, pk=pk)
    n = project.records.count()
    project.records.all().delete()
    messages.success(request, "Removidos {} records.".format(n))
    return redirect("project_detail", pk=pk)


@require_POST
def extract_start(request, pk):
    project = get_object_or_404(Project, pk=pk)
    form = ExtractForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Parametros de extracao invalidos.")
        return redirect("project_detail", pk=pk)
    cd = form.cleaned_data
    started = worker.start_extraction(
        project_id=pk,
        query=cd["query"],
        max_results=cd["max_results"],
        from_year=cd.get("from_year") or 0,
        to_year=cd.get("to_year") or 0,
    )
    if not started:
        messages.warning(request, "Ja existe uma extracao a correr para este projeto.")
    else:
        messages.info(request, "Extracao PubMed iniciada.")
    return redirect("project_detail", pk=pk)


@require_GET
def extract_status_json(request, pk):
    return JsonResponse(worker.extract_status(pk))


# ====================================================================
# Runs de screening
# ====================================================================

@require_POST
def run_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    providers = available_providers()
    provider_choices = [(p["key"], p["label"]) for p in providers if p["available"]]
    form = RunForm(request.POST, provider_choices=provider_choices)
    if not form.is_valid():
        messages.error(request, "Configuracao da run invalida.")
        return redirect("project_detail", pk=pk)
    if project.records.count() == 0:
        messages.error(request, "Adiciona records antes de correr o screening.")
        return redirect("project_detail", pk=pk)

    cd = form.cleaned_data
    run = ScreeningRun.objects.create(
        project=project,
        provider=cd["provider"],
        model=cd["model"],
        prompt_structure=cd["prompt_structure"],
        temperature=cd["temperature"],
        max_tokens=cd["max_tokens"],
        no_think=cd["no_think"],
        status=ScreeningRun.PENDING,
        total=project.records.count(),
    )
    worker.start_screening_run(run)
    messages.success(request, "Screening iniciado (run #{}).".format(run.pk))
    return redirect("run_detail", pk=run.pk)


def run_detail(request, pk):
    run = get_object_or_404(ScreeningRun, pk=pk)
    return render(request, "screening/run_detail.html", {"run": run, "project": run.project})


@require_GET
def run_progress_json(request, pk):
    run = get_object_or_404(ScreeningRun, pk=pk)
    return JsonResponse({
        "status": run.status,
        "processed": run.processed,
        "total": run.total,
        "tokens": run.tokens,
        "pct": run.progress_pct,
        "include_count": run.include_count,
        "error": run.error,
        "active": run.is_active,
    })


@require_POST
def run_cancel(request, pk):
    run = get_object_or_404(ScreeningRun, pk=pk)
    worker.request_cancel(run.pk)
    messages.info(request, "Pedido de cancelamento enviado.")
    return redirect("run_detail", pk=pk)


@require_POST
def run_delete(request, pk):
    run = get_object_or_404(ScreeningRun, pk=pk)
    project_pk = run.project_id
    run.delete()
    messages.success(request, "Run eliminada.")
    return redirect("project_detail", pk=project_pk)


# ====================================================================
# Revisao humana
# ====================================================================

@ensure_csrf_cookie
def run_review(request, pk):
    run = get_object_or_404(ScreeningRun.objects.select_related("project"), pk=pk)
    decision = request.GET.get("decision", "all")
    reviewed = request.GET.get("reviewed", "all")

    qs = run.predictions.select_related("record")
    if decision == "include":
        qs = qs.filter(pred=INCLUDE)
    elif decision == "exclude":
        qs = qs.filter(pred=EXCLUDE)
    elif decision == "unparseable":
        qs = qs.filter(pred=UNPARSEABLE)
    if reviewed == "yes":
        qs = qs.filter(reviewer_decision__isnull=False)
    elif reviewed == "no":
        qs = qs.filter(reviewer_decision__isnull=True)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "run": run,
        "project": run.project,
        "page": page,
        "decision": decision,
        "reviewed": reviewed,
        "INCLUDE": INCLUDE,
        "EXCLUDE": EXCLUDE,
        "UNPARSEABLE": UNPARSEABLE,
    }
    return render(request, "screening/run_review.html", context)


@require_POST
def prediction_decide(request, pk):
    """Override do revisor (chamado por fetch JS). pk = Prediction id."""
    prediction = get_object_or_404(Prediction, pk=pk)
    decision = request.POST.get("decision", "")
    if decision == "include":
        prediction.reviewer_decision = INCLUDE
    elif decision == "exclude":
        prediction.reviewer_decision = EXCLUDE
    elif decision == "reset":
        prediction.reviewer_decision = None
    else:
        return JsonResponse({"ok": False, "error": "decisao invalida"}, status=400)
    prediction.reviewed_at = timezone.now() if prediction.reviewer_decision is not None else None
    prediction.save(update_fields=["reviewer_decision", "reviewed_at"])

    run = prediction.run
    return JsonResponse({
        "ok": True,
        "final_decision": prediction.final_decision,
        "reviewer_decision": prediction.reviewer_decision,
        "final_include_count": run.final_include_count,
        "reviewed_count": run.reviewed_count,
    })


# ====================================================================
# Export
# ====================================================================

EXPORT_FIELDS = [
    "idx", "title", "abstract", "doi", "pmid", "pubmed_url",
    "journal", "authors", "publication_date",
    "llm_pred", "reviewer_decision", "final_decision", "gold_label",
]


def _pred_label(value):
    return {INCLUDE: "include", EXCLUDE: "exclude", UNPARSEABLE: "unparseable"}.get(value, "")


def _export_rows(run):
    rows = []
    preds = run.predictions.select_related("record").all()
    for p in preds:
        if p.final_decision != INCLUDE:
            continue
        rec = p.record
        rows.append({
            "idx": rec.idx,
            "title": rec.title,
            "abstract": rec.abstract,
            "doi": rec.doi,
            "pmid": rec.pmid,
            "pubmed_url": rec.pubmed_url,
            "journal": rec.journal,
            "authors": rec.authors,
            "publication_date": rec.publication_date,
            "llm_pred": _pred_label(p.pred),
            "reviewer_decision": _pred_label(p.reviewer_decision) if p.reviewer_decision is not None else "",
            "final_decision": _pred_label(p.final_decision),
            "gold_label": "" if rec.gold_label is None else rec.gold_label,
        })
    return rows


def run_export(request, pk):
    run = get_object_or_404(ScreeningRun, pk=pk)
    fmt = request.GET.get("format", "csv")
    rows = _export_rows(run)
    base = "run{}_{}_{}_included".format(run.pk, run.provider, run.prompt_structure)

    if fmt == "xlsx":
        try:
            import pandas as pd
        except Exception:  # noqa: BLE001
            messages.error(request, "pandas/openpyxl indisponivel para XLSX; usa CSV.")
            return redirect("run_review", pk=pk)
        df = pd.DataFrame(rows, columns=EXPORT_FIELDS)
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        buf.seek(0)
        resp = HttpResponse(
            buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="{}.xlsx"'.format(base)
        return resp

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = 'attachment; filename="{}.csv"'.format(base)
    return resp
