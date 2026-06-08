"""Modelos: Project, Record, ScreeningRun, Prediction."""

from __future__ import annotations

from django.db import models

PROMPT_STRUCTURE_CHOICES = [
    ("V1", "V1 - single user message (Li 2024)"),
    ("V2", "V2 - system + user (Dennstadt 2024)"),
]

PROVIDER_CHOICES = [
    ("openai", "OpenAI GPT-4o (cloud)"),
    ("deepseek", "DeepSeek-V4-Flash (cloud)"),
    ("groq", "Groq Llama-3.3-70B (cloud)"),
    ("ollama", "Ollama qwen3:8B (local)"),
]

# Decisoes (pred e reviewer_decision)
EXCLUDE, INCLUDE, UNPARSEABLE = 0, 1, -1


class Project(models.Model):
    """Uma revisao sistematica: define instrucao, criterios e defaults de modelo."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    base_prompt = models.TextField(
        help_text="Instrucao generica enviada ao LLM (tema, formato yes/no, restricoes)."
    )
    criteria = models.TextField(
        blank=True, help_text="Criterios de inclusao/exclusao (I/E)."
    )
    prompt_structure = models.CharField(
        max_length=2, choices=PROMPT_STRUCTURE_CHOICES, default="V2"
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="deepseek")
    model = models.CharField(max_length=120, blank=True, help_text="Vazio = default do provider.")
    temperature = models.FloatField(default=0.0)
    max_tokens = models.IntegerField(default=100)
    no_think = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def record_count(self):
        return self.records.count()


class Record(models.Model):
    """Um artigo (title + abstract + metadados opcionais) de um projeto."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="records")
    idx = models.IntegerField(help_text="Indice 0-based dentro do projeto.")
    title = models.TextField()
    abstract = models.TextField(blank=True)

    doi = models.CharField(max_length=200, blank=True)
    pmid = models.CharField(max_length=30, blank=True)
    journal = models.TextField(blank=True)
    authors = models.TextField(blank=True)
    publication_date = models.CharField(max_length=40, blank=True)
    pubmed_url = models.URLField(blank=True)

    gold_label = models.IntegerField(null=True, blank=True, help_text="Gold standard opcional.")

    class Meta:
        ordering = ["idx"]
        unique_together = [("project", "idx")]

    def __str__(self):
        return "[{}] {}".format(self.idx, self.title[:80])


class ScreeningRun(models.Model):
    """Uma execucao do LLM sobre os records de um projeto."""

    PENDING, RUNNING, DONE, ERROR, CANCELLED = "pending", "running", "done", "error", "cancelled"
    STATUS_CHOICES = [
        (PENDING, "Em fila"),
        (RUNNING, "A correr"),
        (DONE, "Concluido"),
        (ERROR, "Erro"),
        (CANCELLED, "Cancelado"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="runs")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    model = models.CharField(max_length=120, blank=True)
    prompt_structure = models.CharField(max_length=2, choices=PROMPT_STRUCTURE_CHOICES)
    temperature = models.FloatField(default=0.0)
    max_tokens = models.IntegerField(default=100)
    no_think = models.BooleanField(default=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    total = models.IntegerField(default=0)
    processed = models.IntegerField(default=0)
    tokens = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return "Run #{} ({} {} {})".format(self.pk, self.provider, self.model or "default", self.prompt_structure)

    @property
    def progress_pct(self):
        if not self.total:
            return 0
        return int(round(100.0 * self.processed / self.total))

    @property
    def is_active(self):
        return self.status in (self.PENDING, self.RUNNING)

    @property
    def include_count(self):
        return self.predictions.filter(pred=INCLUDE).count()

    @property
    def final_include_count(self):
        """Includes apos override do revisor (reviewer_decision tem prioridade)."""
        reviewed_in = self.predictions.filter(reviewer_decision=INCLUDE).count()
        auto_in = self.predictions.filter(reviewer_decision__isnull=True, pred=INCLUDE).count()
        return reviewed_in + auto_in

    @property
    def reviewed_count(self):
        return self.predictions.filter(reviewer_decision__isnull=False).count()


class Prediction(models.Model):
    """Decisao do LLM para um record numa run, com override opcional do revisor."""

    run = models.ForeignKey(ScreeningRun, on_delete=models.CASCADE, related_name="predictions")
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="predictions")
    pred = models.IntegerField(default=UNPARSEABLE, help_text="1 incluir, 0 excluir, -1 nao parseado.")
    per_criterion = models.JSONField(default=list, blank=True)
    raw_response = models.TextField(blank=True)
    reviewer_decision = models.IntegerField(
        null=True, blank=True, help_text="Override humano: 1 incluir, 0 excluir, null = nao revisto."
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["record__idx"]
        unique_together = [("run", "record")]

    def __str__(self):
        return "pred={} rev={} ({})".format(self.pred, self.reviewer_decision, self.record_id)

    @property
    def final_decision(self):
        """Decisao efetiva: override do revisor se existir, senao a do LLM."""
        if self.reviewer_decision is not None:
            return self.reviewer_decision
        return INCLUDE if self.pred == INCLUDE else EXCLUDE
