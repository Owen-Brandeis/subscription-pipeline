# subscription-pipeline

Install Dependencies: python3 -m pip install -r requirements.txt
Run: python3 -m uvicorn app.web:app --reload --port 8000


MVP web app: upload filled packet PDF + outline template PDF → parse/extract → validate → fill template (if configured) → download filled PDF from outbox.

## Setup

1. **Optional:** Create a virtualenv and activate it.
2. Copy `.env.example` to `.env` and set any required env vars (e.g. Reducto API).
3. Install dependencies:

   ```bash
   make bootstrap
   # or: python3 -m pip install -r requirements.txt
   ```

4. Run the environment check:

   ```bash
   make check
   # or: python3 scripts/doctor.py && pytest -q
   ```

## Running the web UI

```bash
make web
# or: python3 -m uvicorn app.web:app --reload --port 8000
```

Open http://localhost:8000. Upload:

- **Packet PDF (required):** filled subscription packet to parse and extract from.
- **Outline template PDF (required):** flat PDF template to fill with extracted data.

After you submit, the app shows a **progress page** with a bar and live updates (Server-Sent Events). When processing finishes it redirects to the result page with download links.

**Progress is stored in memory** (per process). It does not survive a server restart; for multi-worker or persistent progress you could later move to Redis or another store.

## What gets produced

- **`artifacts/<case_id>/`**  
  - `inputs/packet.pdf`, `inputs/template.pdf` — your uploads  
  - `extracted.json`, `canonical.json`, `validation_report.json` — extraction and validation  
  - `filled.pdf` — only if the template has a non-empty field mapping  
  - `template_config_used.json` — config used for this run  

- **`artifacts/_templates/<template_id>/`**  
  - `template.pdf`, `template_config.json`, `detected_fields.json` — template storage and optional mapping  

- **`outbox/`**  
  - `<case_id>_filled.pdf`, `<case_id>_canonical.json`, `<case_id>_validation_report.json` — after a successful fill you can download from the UI or copy from here  

## Template mapping

Flat PDFs have no form fields; the app fills them using a **template config** that maps schema paths (e.g. `investor.legal_name`) to bounding boxes and types (text, multiline, checkbox, date). Config is keyed by the template PDF’s SHA-256.

- If a matching config with non-empty `fields` exists under `artifacts/_templates/**/template_config.json`, it is used and a filled PDF is produced.
- If not, the app runs template analysis, writes a **starter** `template_config.json` with `fields: []`, and shows a result page: **"Template mapping not configured yet. No filled PDF produced."** with a link to download the starter config. Configure fields (e.g. with the template builder), save the config under `_templates/<template_id>/template_config.json`, then re-run.

## Troubleshooting

- **"Packet PDF upload is missing or has no filename"** — Select both PDFs in the form before submitting.
- **"Template mapping not configured yet"** — Download the starter `template_config_used.json`, add `schema_path` and `bbox` (and type) for each field, save as `artifacts/_templates/<template_id>/template_config.json`, and run again. Use `scripts/run_template_builder.py` to build config visually.
- **Pipeline or fill errors** — Check server logs (stderr). If a `validation_report.json` exists for the case, the error page will include a link to download it.
- **Filled PDF is blank or text missing** — The app assigns default schema paths (investor.legal_name, investment.amount.value, signatures[0].signer_name) to the first three text fields when the template has none set. Run `python3 scripts/diagnose_fill.py <case_id>` to see which fields have `schema_path` and what values are looked up from canonical data. Ensure `artifacts/<case_id>/canonical.json` has the expected structure; if the overlay is correct but the merged PDF hides it, the filler uses black text and merges the overlay on top (`over=True`).
- **Outbox downloads** — After a successful fill, use the **Download Filled PDF** link on the result page, or open `outbox/<case_id>_filled.pdf` on disk. Only `.pdf` and `.json` filenames are allowed from `/download_outbox/<filename>`.
- **Tests** — Run `make check` or `pytest -q`. Tests do not call external APIs (pipeline/filler are mocked where needed).
