# Contract Derisking System

An AI-assisted contract review tool. Upload one contract or a whole folder
of them (text PDFs or scans). For every contract the system:

- extracts the text, using OCR for scanned pages;
- separates the contract header (parties, lender, financed amount) from
  the clauses;
- classifies each clause by domain and risk level;
- checks it against your policy library;
- extracts key facts (borrower, lender, amount, dates);
- writes an executive summary.

A chatbot then answers questions across all your contracts. Rankings,
totals and counts are computed exactly from the stored data, clause
questions are answered from the clause text with references, and each
reference jumps to the highlighted clause in the original PDF.

The project has two parts:

- **`backend/`**: a Python / FastAPI service for parsing, LLM analysis,
  search and chat.
- **root (`src/`)**: a Vite + React + TypeScript frontend (shadcn-ui,
  Tailwind).

---

## Quick start (Windows)

1. **Backend**: in PowerShell:
   ```powershell
   cd backend
   pip install -r requirements.txt
   python run_server.py
   ```
   Wait for `Uvicorn running on http://0.0.0.0:8001`.
2. **Frontend**: in a second PowerShell window, from the repo root:
   ```powershell
   npm install
   npm run dev
   ```
   Open the address it prints (usually http://localhost:8080).
3. **Upload your contracts**: go to **Upload Contracts**, click **Choose
   folder**, and pick the folder with your PDFs.
4. **Ask questions**: go to **Chatbot**.

The AI models are configured in `backend/app/settings.json` (see
[Configuration](#configuration)).

---

## Features

### Upload: single files or whole folders

- The **Upload Contracts** page takes several files, a whole folder
  (sub-folders included), or files dragged onto it.
- Contracts are uploaded and analyzed **one after another** with a
  per-file progress list. The batch keeps running while you use other
  pages. **Stop after current file** halts it, and **Retry failed** re-runs
  only the files that failed.
- **Re-running the same folder is cheap.** Files that are already stored
  and analyzed, with unchanged text, are not analyzed again.
- The same file under another name (e.g. a copy in a sub-folder) is
  recognised by its content and not stored twice.
- Non-PDF files are listed as skipped.

### Text extraction and clause splitting (`backend/app/parser.py`)

- PDFs are read directly. **OCR (Tesseract) is decided page by page**, so a
  scan that has a small text footer ("Scanned with …"), or a typed cover
  page followed by scanned pages, is still read.
- **Page furniture** is removed before clauses are split: page numbers
  ("Page 2 of 5") and running headers or footers repeated on most pages.
  The first copy of a repeated line is kept, so a real heading repeated
  on every page is never lost. Numbered schedule rows are kept.
- The **contract header** (title, parties, amounts before the first
  clause) is stored separately from the clauses. It's shown and
  searchable, but it is never risk-scored as a clause.
- Clause headings are recognised in both numbered form (`2. TERM`) and
  keyword form (`CLAUSE ONE – PURPOSE`, `Article 1: Term`, `Section Two -
  Payment`).
- A **parse-quality check** flags documents where text didn't end up in
  any clause.

### Contract facts (`backend/app/mcp/llm_agent.py`, `parser.py`)

- One LLM call per contract extracts the borrower/customer, lender,
  contract type, start and end dates, amount and currency, governing law,
  and whether there's an indemnification clause.
- **Grounding**:
  - A value the document states under an explicit label
    (`FINANCED AMOUNT: $45,892.00`, `LENDER: …`) always wins over the
    model's reading.
  - An unlabeled value from the model is kept only if it's actually
    found in the text; otherwise it's discarded, with a warning recorded
    in `extraction_warnings`.
  - `field_sources` records where each value came from.
- **The label reader handles:**
  - names with abbreviations and initials: "Mr. John A. Smith",
    "J.P. Morgan Chase Bank", "Acme Pvt. Ltd.";
  - labels in any case: `LENDER:`, `Lender:`, `Address:`;
  - amounts written out in words with the figure after them;
  - US, Indian (`₹4,58,920.00`) and European (`EUR 45.892,00`) number
    formats;
  - USD, INR, EUR, GBP, BRL, CAD and other currency codes.

### Risk analysis and policy compliance (`backend/app/policy.py`)

- Each clause is classified by domain (Financial, Legal, Compliance, …)
  and risk level (High / Medium / Low).
- Clauses are checked against the **policy library**, which you edit on
  the Policies page:
  - Edits are saved in your browser and used by every new analysis.
    **Reset to defaults** restores the built-in library.
  - The page flags policies whose category isn't one of the analysis
    domains; those are never used.
- A check is satisfied if *any* clause in its domain satisfies it. It is
  only a violation if *no* clause in the contract does. Violations appear
  on the contract page as **Missing Requirements**.

### When the AI server struggles

The models run on a shared Ollama server, which can be busy.

- **Retries**: server errors (5xx) and dropped connections are retried
  with a short back-off, for both LLM calls and embeddings. Timeouts
  aren't retried, because each one already waited the full
  `llm_timeout_sec`.
- **Partial analysis**: if the model can't classify some clauses, they are
  scored by keyword matching, retried once at the end, and the contract
  is marked **"Partial analysis"** with an explanation. It is never
  silently presented as a normal result.
- **Unknown, not low**: a contract that hasn't been risk-analyzed shows as
  **"Not analyzed"** everywhere, and is left out of risk figures instead
  of counting as low risk. Its page has a **Run analysis** button.
- **Nothing good is overwritten**: if re-processing a file happens while
  the AI server is down, the previous good extraction is kept.
- **Search failures are recorded**: if a contract couldn't be added to
  chat search, that's stored on the contract and reported.

### Chatbot (`backend/app/chat_router.py`, `main.py` → `/chat`)

Each question is first classified by the model into a small, validated
query spec.

**Structured questions** are answered **exactly, in code**, from the
stored facts and risk figures, never by the model doing arithmetic:

- rankings: highest / lowest / top N / **second highest**;
- counts, totals, averages;
- filters by lender, date or amount, including "above 50k" and
  "1.5 million";
- risk: **"which contracts have the highest risks"**, ranked by high-risk
  clauses (ties broken by medium-risk clauses);
- grouping: **"which lender has the most contracts"**.

Under each answer the chat shows how it was produced: **"Exact answer
computed from the contract data"** or **"Answered by <model> from the
contract text"**. The backend log also prints `[chat] answered by …`.

Rankings, counts and totals always cover **all** contracts, even when
one contract is open. Different currencies are never compared or added
together. Each answer says how many contracts it covers.

**Clause questions** ("what's the interest rate in Julia Miller's
contract?", "which contracts charge more than 1.4%?") are answered by
the model from clause text:

- A question that names a contract (by file name or borrower name) reads
  that contract.
- A question about all contracts looks at the best passage from
  **every** contract, not just a handful.
- Otherwise the model is told how much of the portfolio its sources
  cover.
- Follow-ups ("and for Peter?") are rewritten into standalone questions
  before searching.
- The model must cite its sources, only the cited sources are listed,
  and it may not infer risk from amounts.

**References** open the contract on the right and highlight the exact
clause in the original PDF, including clauses that run onto the next
page. Clicking a reference only changes the document shown; the question
scope stays whatever you picked in the dropdown.

If the classification step fails, plain amount questions ("which
contract has the highest amount?", "how many contracts are there?",
"riskiest contract") are still answered exactly by fallback rules.

---

## Configuration

`backend/app/settings.json`:

```json
{
  "provider": "ollama",
  "ollama_url": "https://librechat.eplpg.com/ollama",
  "ollama_model": "qwen3:8b",
  "ollama_quality_model": "qwen3:8b",
  "ollama_verify_ssl": false,
  "llm_concurrency": 4,
  "ollama_num_ctx": 16384,
  "llm_timeout_sec": 240,
  "embedding_url": "",
  "embedding_model": "qwen3-embedding:8b",
  "ollama_chat_model": "qwen3:32b",
  "ollama_chat_fallback_models": ["gpt-oss:20b", "qwen3:8b"]
}
```

| Key | Meaning |
|---|---|
| `ollama_model` | Model for per-clause work (classification, compliance checks) |
| `ollama_quality_model` | Model for per-contract work: fact extraction, summaries, question routing. Also the last fallback for chat answers. |
| `ollama_chat_model` | Optional: a bigger model for writing chat answers, e.g. `qwen3:32b` (needs about 13.5 GB free on the server). |
| `ollama_chat_fallback_models` | Models tried next, in order, if the chat model can't answer (out of memory, timeout, error), e.g. `["gpt-oss:20b", "qwen3:8b"]`. The chat shows which model answered. |
| `ollama_num_ctx` | Context window. Must be large enough for whole-contract chat prompts; answers are refused rather than silently truncated if a prompt doesn't fit. |
| `llm_concurrency` | How many LLM calls run in parallel during one analysis |
| `llm_timeout_sec` | How long to wait for one model answer |
| `embedding_model` | Model for chat search. Each embedding model gets its own search index; after changing it, run a re-index (below). |
| `embedding_url` | Embedding server, if different from `ollama_url` (empty = same) |
| `ollama_verify_ssl` | Set `false` for a server with a self-signed certificate |
| `rag_min_score`, `rag_relative_margin` | Optional search tuning (defaults are per embedding model) |

Groq is also supported (`"provider": "groq"`, `groq_model`, and a
`GROQ_API_KEY` environment variable).

**Ports.** The backend runs on **8001** (`run_server.py`,
`start_backend.bat`). The frontend expects it at
`http://localhost:8001`; set `VITE_API_URL` in a `.env` file in the
repo root if it runs elsewhere.

**OCR** needs Tesseract and Poppler installed (see `TESSERACT_SETUP.md`
and `OCR_FEATURES.md`). The backend prints `[OK] Poppler configured at:
…` on startup when it finds Poppler.

---

## Maintenance

### Re-index all contracts

This re-parses every stored contract with the current code, re-extracts
its facts, rebuilds the chat search index, and re-analyzes contracts
whose clauses changed:

```powershell
Invoke-RestMethod -Uri "http://localhost:8001/admin/reindex?remove_duplicates=true" -Method Post
Invoke-RestMethod -Uri "http://localhost:8001/admin/reindex/status" -Method Get
```

Poll the status until `phase` is `finished`, and check `results`,
`needs_analysis` and `not_searchable`. The options are:
- `reanalyze=changed|all|none` (default `changed`);
- `remove_duplicates=true` to delete extra copies of the same file;
- `reset_index=true|false` (default `true`) to rebuild the search index
  from scratch.

### Start from an empty library

Stop the backend, then move the data aside. Keep `data\policies`.

```powershell
cd backend
$backup = "..\old-data-" + (Get-Date -Format yyyyMMdd-HHmm)
mkdir $backup
Move-Item data\analyses.json, qdrant_data, uploaded_files $backup
```

Start the backend again and re-upload the folder.

### Tests

```powershell
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q
```

- The tests use a fake LLM and fake embeddings, so they run offline in
  seconds. Their data goes to a temporary folder.
- The OCR tests also need `reportlab`, and the real-OCR test needs
  Tesseract and Poppler on the `PATH`; otherwise they are skipped.
- Run the tests from `backend\`: `test_run.py` in that folder is a
  server launcher, not a test file, so pass `tests` as shown above.

### Checking answers against the real models

The tests prove the logic, not the real model's behaviour on your
contracts. For that:

1. Put real questions in `backend/scripts/eval_questions.json`, with
   answers you've checked yourself in the documents.
2. With the backend running, run `python scripts/eval_chat.py`.

Run it after any change to models, prompts, parsing or settings: a
question that passed before and fails now is a regression.

---

## Project structure

```
backend/
  app/
    main.py            API: upload, analyze, chat, contracts, summary, compare, re-index
    chat_router.py     Question routing + exact answers (rankings, totals, risk, grouping)
    parser.py          Text extraction, OCR, page-furniture removal, clause splitting, labeled facts
    rag.py             Chat search over a local Qdrant index (retries, per-contract search)
    llm_providers.py   Ollama / Groq calls (retries, context-overflow detection)
    schemas.py         Validated shapes of every model answer; amount parsing
    policy.py          Policy library storage + compliance evaluation
    store.py           Contract records (JSON file, atomic writes)
    mcp/llm_agent.py   Classification, fact extraction + grounding, summaries
    settings.json      Model / server configuration
  data/                Stored contracts and policies (not committed)
  uploaded_files/      Original uploaded files (not committed)
  qdrant_data/         Chat search index (not committed)
  tests/               Automated tests (pytest)
  scripts/             eval_chat.py - checks the live chatbot
  run_server.py        Starts the backend on port 8001
src/
  pages/               Upload, Analyses, AnalysisDetail, Policies, Dashboard, Insights, Compare, Chat
  components/          DocumentViewer / PdfDocumentViewer (clause highlighting), UI components
  lib/                 uploadQueue (folder upload), chatSession, pdfHighlight, analysisStatus
  policy/              Built-in policy library + compiler
  services/            API client
```

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/upload` | Upload one contract (the same file twice updates the existing record) |
| POST | `/upload/batch` | Upload several contracts |
| POST | `/analyze` | Classify clauses, check policy compliance, write the summary |
| GET | `/clauses`, `/clauses/{id}` | List contracts / get one (with header, clauses, results) |
| GET | `/clauses/{id}/file` | The original uploaded file |
| GET | `/contracts` | Contracts with extracted facts |
| POST | `/chat` | Ask a question (optionally about one contract via `analysis_id`) |
| POST | `/compare` | Compare two contracts |
| POST | `/summary/{id}` | Regenerate the executive summary |
| POST | `/recommend` | Suggest alternative wording for a clause |
| POST | `/admin/reindex`, GET `/admin/reindex/status` | Re-parse, re-extract and re-index everything |
| GET / POST | `/settings`, GET `/settings/test` | View / change model settings, test the connection |

The full list with request/response schemas is at
`http://localhost:8001/docs` while the backend runs.

---

## Known limitations

- **Treat AI judgments as a starting point for legal review**, not a
  verdict: risk levels, policy compliance and clause answers can be
  wrong on unusual wording.
- **Scanned PDFs**: the viewer can jump to the right page but can't
  highlight text, because scans have no text layer.
- **Single-page documents**: a running header on a single-page document
  can't be told apart from content, so it stays in the header text.
- **Policy edits are per browser**: they're stored in that browser, so
  another browser or computer uses the built-in library until edited
  there too.
- **Single user**: data is stored in local files (`backend/data`,
  `qdrant_data`). This suits one user; it isn't a multi-user production
  datastore. Run only one backend process at a time.
- **Shared AI server**: analysis speed depends on how busy it is.
  Bigger models may not fit in its memory; see `ollama_quality_model`
  above.
