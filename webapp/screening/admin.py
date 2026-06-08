from django.contrib import admin

from .models import Prediction, Project, Record, ScreeningRun


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "model", "prompt_structure", "record_count", "created_at")
    search_fields = ("name", "description")


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ("project", "idx", "title", "gold_label")
    list_filter = ("project",)
    search_fields = ("title", "abstract", "doi", "pmid")


@admin.register(ScreeningRun)
class ScreeningRunAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "provider", "model", "prompt_structure", "status",
                    "processed", "total", "tokens", "created_at")
    list_filter = ("status", "provider", "prompt_structure")


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("run", "record", "pred", "reviewer_decision")
    list_filter = ("run", "pred")
