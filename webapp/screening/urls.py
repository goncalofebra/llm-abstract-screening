from django.urls import path

from . import views

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("settings/", views.settings_view, name="settings"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="project_delete"),

    # popular records
    path("projects/<int:pk>/upload/", views.upload_records, name="upload_records"),
    path("projects/<int:pk>/clear/", views.records_clear, name="records_clear"),
    path("projects/<int:pk>/extract/", views.extract_start, name="extract_start"),
    path("projects/<int:pk>/extract/status/", views.extract_status_json, name="extract_status"),

    # runs
    path("projects/<int:pk>/run/", views.run_create, name="run_create"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/progress/", views.run_progress_json, name="run_progress"),
    path("runs/<int:pk>/cancel/", views.run_cancel, name="run_cancel"),
    path("runs/<int:pk>/delete/", views.run_delete, name="run_delete"),

    # revisao + export
    path("runs/<int:pk>/review/", views.run_review, name="run_review"),
    path("predictions/<int:pk>/decide/", views.prediction_decide, name="prediction_decide"),
    path("runs/<int:pk>/export/", views.run_export, name="run_export"),
]
