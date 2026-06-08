# Web application (Django)

Local, single-user web interface for the LLM Title/Abstract screening pipeline.
It implements the human-in-the-loop workflow: define a project, populate a corpus
(PubMed query or file upload), run the screening in the background with live progress,
review and override the model's decisions, and export the confirmed inclusion list.

## Requirements

- Python 3.9 to 3.12 with the project dependencies installed (`pip install -r ../requirements.txt`).
- API key for a cloud provider in `../pipeline/.env` (or set it on the **Settings** page).
  The local model (Ollama / Qwen3) needs no key.

## Run

From the repository root, create and activate a virtual environment and install the
dependencies (see the top-level README), then:

```bash
cd webapp
python manage.py migrate        # first run only (creates db.sqlite3)
python manage.py runserver
```

Open **http://localhost:8000**. On Windows you can also double-click `run.bat`
(with the virtual environment active), or run `./run.ps1`.

## Usage

1. **New project** — name, base prompt (a sensible default is pre-filled), inclusion/exclusion
   criteria, prompt structure (V1/V2), default provider and model.
2. **Populate the corpus** — run a PubMed query in the interface, or upload a file:
   `.txt` (native `Title:`/`Abstract:` format), `.csv`, or `.xlsx` (Citations Export).
3. **Run screening** — choose provider/model/parameters; a background worker processes the
   corpus and the page shows a live progress bar (cancellable).
4. **Review** — confirm or override each decision; included articles are highlighted.
5. **Export** — download the confirmed inclusion set (CSV/XLSX) with DOIs.

## Configuration notes

- This is a **local development** configuration: `DEBUG=True`, SQLite, no authentication,
  and a placeholder dev `SECRET_KEY`. Do not deploy it to a public server without hardening
  (real `SECRET_KEY`, `DEBUG=False`, authentication, allowed hosts).
- Long runs execute in a background thread (no Celery/Redis); SQLite uses WAL mode so the
  worker and web requests can access the database concurrently.
- The app imports the shared `screening_core` module from `../pipeline/`, guaranteeing that
  interactive runs and command-line runs produce identical decisions.
