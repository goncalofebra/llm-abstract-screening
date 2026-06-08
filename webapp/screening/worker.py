"""
Worker em background (threads daemon) para runs de screening e extracoes PubMed.

Sem Redis/Celery: para uso local single-user, um thread por tarefa e' suficiente.
A escrita incremental de Prediction faz os resultados aparecerem em streaming
na pagina de revisao; o progresso e' lido por polling JSON.
"""

from __future__ import annotations

import os
import threading
import traceback
from typing import Dict

from django.db import connection
from django.utils import timezone

import screening_core
from screening_core import PROVIDERS, ScreenConfig, make_client, screen_one

from .models import EXCLUDE, INCLUDE, UNPARSEABLE, Prediction, Record, ScreeningRun

# Eventos de cancelamento por run_id.
_cancel_events: Dict[int, threading.Event] = {}
_lock = threading.Lock()

# Estado em memoria das extracoes PubMed, por project_id (protegido por _lock).
EXTRACT_JOBS: Dict[int, Dict[str, object]] = {}

# Serializa a criacao de records (extract/upload) para evitar colisoes de idx.
_append_lock = threading.Lock()


def append_records(project, record_dicts) -> int:
    """
    Acrescenta records a um projeto de forma atomica e serializada.
    Calcula o proximo idx via Max(idx)+1 dentro de transaction.atomic e sob lock,
    eliminando colisoes do unique_together(project, idx) quando upload e extracao
    (ou dois uploads) correm em simultaneo. Devolve o numero de records criados.
    """
    from django.db import transaction
    from django.db.models import Max

    with _append_lock:
        with transaction.atomic():
            base = project.records.aggregate(m=Max("idx"))["m"]
            start_idx = 0 if base is None else base + 1
            objs = []
            for offset, rec in enumerate(record_dicts):
                objs.append(Record(
                    project=project,
                    idx=start_idx + offset,
                    title=rec.get("title", ""),
                    abstract=rec.get("abstract", ""),
                    doi=rec.get("doi", ""),
                    pmid=rec.get("pmid", ""),
                    journal=rec.get("journal", ""),
                    authors=rec.get("authors", ""),
                    publication_date=rec.get("publication_date", ""),
                    pubmed_url=rec.get("pubmed_url", ""),
                    gold_label=rec.get("gold_label"),
                ))
            Record.objects.bulk_create(objs, batch_size=500)
    return len(objs)


# ====================================================================
# Screening
# ====================================================================

def request_cancel(run_id: int) -> None:
    with _lock:
        event = _cancel_events.get(run_id)
    if event is not None:
        event.set()


def is_run_active(run_id: int) -> bool:
    with _lock:
        return run_id in _cancel_events


def start_screening_run(run: ScreeningRun) -> None:
    """Lanca um thread daemon que corre o screening da run."""
    event = threading.Event()
    with _lock:
        _cancel_events[run.pk] = event
    thread = threading.Thread(target=_run_screening, args=(run.pk, event), daemon=True)
    thread.start()


def _resolve_api_key(provider: str) -> str:
    prov = PROVIDERS[provider]
    key = os.getenv(prov["key_env"], "")
    if provider == "ollama" and not key:
        return "ollama"
    return key


def _run_screening(run_id: int, event: threading.Event) -> None:
    try:
        run = ScreeningRun.objects.select_related("project").get(pk=run_id)
        project = run.project
        records = list(project.records.all())

        run.status = ScreeningRun.RUNNING
        run.started_at = timezone.now()
        run.total = len(records)
        run.processed = 0
        run.tokens = 0
        run.error = ""
        run.save()

        if not records:
            run.status = ScreeningRun.ERROR
            run.error = "O projeto nao tem records para screenar."
            run.finished_at = timezone.now()
            run.save()
            return

        config = ScreenConfig(
            provider=run.provider,
            model=run.model,
            prompt_structure=run.prompt_structure,
            base_prompt=project.base_prompt,
            criteria=project.criteria,
            temperature=run.temperature,
            max_tokens=run.max_tokens,
            no_think=run.no_think,
            api_key=_resolve_api_key(run.provider),
        )

        if run.provider != "ollama" and not config.api_key:
            run.status = ScreeningRun.ERROR
            run.error = "Chave de API em falta para o provider '{}' (define {} no pipeline/.env).".format(
                run.provider, PROVIDERS[run.provider]["key_env"]
            )
            run.finished_at = timezone.now()
            run.save()
            return

        try:
            client = make_client(config)
        except Exception as exc:  # noqa: BLE001
            run.status = ScreeningRun.ERROR
            run.error = "Falha a inicializar o cliente LLM: {}".format(exc)
            run.finished_at = timezone.now()
            run.save()
            return

        total_tokens = 0
        cancelled = False

        for i, rec in enumerate(records):
            if event.is_set():
                cancelled = True
                break
            try:
                result = screen_one(rec.title, rec.abstract, config, client=client)
            except Exception as exc:  # noqa: BLE001
                # Primeira chamada a falhar -> provavelmente erro de config; aborta.
                if i == 0:
                    run.status = ScreeningRun.ERROR
                    run.error = "Erro na 1.a chamada ao LLM: {}".format(exc)
                    run.finished_at = timezone.now()
                    run.save()
                    return
                # A meio: regista como nao-parseado e continua.
                Prediction.objects.create(
                    run=run, record=rec, pred=UNPARSEABLE,
                    per_criterion=[], raw_response="[erro API] {}".format(exc),
                )
                ScreeningRun.objects.filter(pk=run_id).update(processed=i + 1, tokens=total_tokens)
                continue

            Prediction.objects.create(
                run=run, record=rec, pred=result.pred,
                per_criterion=result.per_criterion, raw_response=result.raw_response,
            )
            total_tokens += result.tokens
            ScreeningRun.objects.filter(pk=run_id).update(processed=i + 1, tokens=total_tokens)

        final = ScreeningRun.objects.get(pk=run_id)
        if cancelled:
            final.status = ScreeningRun.CANCELLED
        else:
            final.status = ScreeningRun.DONE
            final.processed = len(records)
        final.tokens = total_tokens
        final.finished_at = timezone.now()
        final.save()

    except Exception:  # noqa: BLE001 - rede de seguranca
        tb = traceback.format_exc()
        # Tenta marcar ERROR de forma resiliente (locks transitorios de SQLite).
        for attempt in range(3):
            try:
                connection.close()  # forca ligacao fresca
                ScreeningRun.objects.filter(pk=run_id).update(
                    status=ScreeningRun.ERROR,
                    error="Erro inesperado:\n{}".format(tb),
                    finished_at=timezone.now(),
                )
                break
            except Exception:  # noqa: BLE001
                import time as _time
                _time.sleep(1 + attempt)
    finally:
        with _lock:
            _cancel_events.pop(run_id, None)
        connection.close()


# ====================================================================
# Extracao PubMed
# ====================================================================

def start_extraction(project_id: int, query: str, max_results: int,
                     from_year: int, to_year: int) -> bool:
    """Arranca uma extracao. Devolve False se ja houver uma a correr (guard atomico)."""
    with _lock:
        cur = EXTRACT_JOBS.get(project_id)
        if cur and cur.get("status") == "running":
            return False
        EXTRACT_JOBS[project_id] = {
            "status": "running", "downloaded": 0, "total": 0, "error": "", "created": 0,
        }
    thread = threading.Thread(
        target=_run_extraction,
        args=(project_id, query, max_results, from_year, to_year),
        daemon=True,
    )
    thread.start()
    return True


def extract_status(project_id: int) -> Dict[str, object]:
    with _lock:
        job = EXTRACT_JOBS.get(project_id)
        return dict(job) if job else {"status": "idle"}


def _run_extraction(project_id: int, query: str, max_results: int,
                    from_year: int, to_year: int) -> None:
    from django.conf import settings
    from .models import Project

    job = EXTRACT_JOBS[project_id]
    try:
        def on_progress(downloaded, total):
            job["downloaded"] = downloaded
            job["total"] = total

        records = screening_core.pubmed_extract(
            query=query,
            max_results=max_results,
            from_year=from_year,
            to_year=to_year,
            api_key=getattr(settings, "NCBI_API_KEY", ""),
            email=getattr(settings, "NCBI_EMAIL", ""),
            on_progress=on_progress,
        )

        project = Project.objects.get(pk=project_id)
        created = append_records(project, records)

        job["created"] = created
        job["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        connection.close()
