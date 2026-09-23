# Contract Derisking System

An AI-assisted contract review tool. Upload a contract (PDF, scanned or
text-based), and the system splits it into clauses, classifies each one
by domain and risk level, checks it against a policy library you define,
extracts structured contract metadata (customer, dates, value, IP terms),
generates an executive summary, and lets you ask a chatbot questions
across your whole contract library.

The project has two parts:

- **`backend/`** — a Python/FastAPI service that does the actual
  parsing, LLM analysis, and policy evaluation.
- **root (`src/`)** — a Vite + React + TypeScript frontend (shadcn-ui,
  Tailwind) that calls the backend and displays the results.

---

## What it does

- **Upload & clause splitting** (`backend/app/parser.py`) — extracts
  text from PDFs (with OCR fallback for scanned documents — see
  `OCR_FEATURES.md` / `TESSERACT_SETUP.md`) and splits it into
  individual clauses. Recognizes both numbered ALL-CAPS headings
  (`"2. TERM"`) and keyword-based headings (`"CLAUSE ONE – PURPOSE"`,
  `"Article 1: Term"`, `"Section Two - Payment"`). Automatically
  deduplicates clauses that appear more than once in the extracted text
  (a known artifact of some PDF generators that reprint the same clause
  list on every page).
- **Contract metadata extraction** (`backend/app/mcp/llm_agent.py`) —
  at upload time, one LLM call extracts customer name, what the
  contract is about, start/end dates, contract value and currency,
  whether IP is shared with the customer, whether an indemnification
  clause exists and how strong it is, and governing law. This is what
  lets the chatbot answer questions like "list contracts ending by
  November 2026" or "what's IDFC's contract value" from real structured
  data instead of guessing from filenames.
- **Clause classification** — each clause is classified by domain
  (Financial, Legal, Privacy, Security, etc.) and risk level
  (High/Medium/Low), with an LLM-based classifier and a deterministic
  keyword-based fallback if no LLM provider is configured.
- **Policy compliance** (`backend/app/policy.py`) — you define a policy
  library (domains, each with named checks and risk weights; see
  `/policy` endpoints). Compliance is evaluated **per check, across the
  whole contract** — a check is satisfied if *any* clause in its domain
  satisfies it; it's only a genuine violation if *no* clause anywhere in
  the contract does. A domain the contract has no clauses in at all is
  treated as not applicable by default (skipped, not penalized) unless
  that domain is explicitly marked `"required": true` in the policy.
- **Executive summary** — generated automatically once a contract has
  been analyzed (obligations, major risks, recommendations, overall
  sentiment), reusing the same LLM extraction pattern as the metadata
  step.
- **Chat** — ask questions about a single contract or across your whole
  contract library. When asking across all contracts, the assistant is
  given a structured directory (not just filenames) built from the
  extracted metadata above.

---

## Project structure

```
backend/
  app/
    main.py            FastAPI app: upload, analyze, policy, chat, contracts endpoints
    parser.py           Text extraction + clause splitting
    policy.py            Policy library storage + compliance evaluation
    store.py             Analysis storage (JSON-backed)
    rag.py                Vector search (Qdrant) for chat context retrieval
    llm_providers.py    Groq / Ollama provider abstraction
    mcp/
      llm_agent.py      LLM-based classification, metadata extraction, summary, policy judgment
      utils.py            Shared JSON-parsing helpers for LLM responses
  data/                  Runtime data (policies, stored analyses) - not committed
  requirements.txt
src/                      React + TypeScript frontend
  pages/                 Upload, AnalysisDetail, Policies, Dashboard, Chat
  components/
  services/               API client functions
```

Also in the repo root: `INSTALLATION_GUIDE.md` (detailed setup),
`OCR_FEATURES.md` and `TESSERACT_SETUP.md` (scanned-PDF OCR setup),
and `architecture.md` (system design notes). This README is the quick
start; see those for more depth on a specific area.

---

## Setup

### Prerequisites

- Python 3.10+
- Node.js + npm ([install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating))
- An LLM provider — either:
  - **Ollama**, running locally (default), or
  - **Groq** API key, for hosted inference

### Backend

```sh
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Configure the LLM provider in `backend/app/settings.json`:

```json
{
  "provider": "ollama",
  "ollama_url": "http://127.0.0.1:11434",
  "ollama_model": "qwen2.5:7b",
  "groq_model": "llama-3.1-70b-versatile"
}
```

- For **Ollama**: make sure Ollama is installed and running, and the
  model named in `ollama_model` has been pulled (`ollama pull
  qwen2.5:7b`).
- For **Groq**: set `"provider": "groq"` and export an API key:
  ```sh
  export GROQ_API_KEY=your-key-here
  ```

If no provider is reachable, the system still runs — LLM-based steps
(classification, metadata extraction, policy compliance judgment,
summaries) fall back to deterministic keyword-based heuristics rather
than failing, but results will be meaningfully less accurate. Check
your backend logs for `"...failed. Using local fallback"` messages if
results look off.

Start the API server:

```sh
uvicorn app.main:app --reload --port 8000
```

### Frontend

```sh
npm install
npm run dev
```

By default the frontend expects the backend at `http://localhost:8000`
— check `src/services/analysis.ts` if you've changed the backend port.

---

## Using it

1. Upload a contract on the Upload page. It's parsed into clauses,
   classified, checked against your chosen policy, and metadata is
   extracted automatically.
2. On the analysis detail page: risk breakdown, executive summary,
   per-clause classification, and a **Missing Requirements** panel
   showing genuine, contract-wide policy gaps (not per-clause noise).
3. On the Policies page, define or edit policy libraries — each domain
   has a list of checks (`name`, `check` description, `risk_weight`),
   and can optionally be marked `"required": true` if that domain's
   total absence from a contract should itself count as a violation.
4. Use the chat to ask questions about one contract, or across all of
   them (e.g. "list contracts ending by November 2026", "which
   contracts share IP with the customer", "what's IDFC's contract
   value").

### Backfilling existing contracts

Contracts uploaded before the metadata-extraction or auto-summary
features existed won't have that data until you backfill:

```sh
curl -X POST http://localhost:8000/contracts/backfill-metadata
```

Add `?force=true` to re-extract for every contract, not just ones
missing metadata. To backfill the executive summary for old contracts,
re-run analysis on them (`POST /analyze`) or use the manual "Generate
Summary" button on the contract's detail page.

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/upload` | Upload a single contract |
| POST | `/upload/batch` | Upload multiple contracts |
| POST | `/analyze` | Classify clauses, run policy compliance, generate the executive summary |
| GET | `/contracts` | List all contracts with extracted metadata |
| POST | `/contracts/backfill-metadata` | Extract metadata for contracts uploaded before this feature existed |
| GET | `/summary/{analysis_id}` | Manually (re)generate the executive summary |
| POST | `/policy` | Save a policy (domains, checks, risk weights) |
| GET | `/policy/{policy_id}` | Fetch a saved policy |
| POST | `/chat` | Ask a question about one contract or across all of them |

Run the server and check `http://localhost:8000/docs` for the full,
current list with request/response schemas.

---

## Known limitations

- Policy compliance judgments (via LLM) can still be wrong on unusual
  phrasing; treat flagged items as a starting point for legal review,
  not a final verdict.
- A clause that's misclassified into the wrong domain (e.g. "Other"
  instead of "Legal") will be checked against the wrong policy checks,
  or none at all if its domain has no defined checks.
- Data is stored as local JSON files (`backend/data/`) — fine for
  single-user/dev use, not intended as a production datastore.
  