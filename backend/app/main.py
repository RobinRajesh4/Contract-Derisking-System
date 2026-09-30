from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from typing import List as TypingList
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import orjson
import os
from dotenv import load_dotenv
import re
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Load env from .env (GROQ_API_KEY, QDRANT_URL, etc.)
load_dotenv()

from .parser import (
    extract_text_from_file,
    split_document,
    extract_metadata,
    assign_clause_pages,
    coverage_report,
)
from .store import Store
from .mcp.llm_agent import LLMClient
from .policy import save_policy, get_policy, list_policies, apply_policy
from .llm_providers import (
    EDITABLE_SETTINGS,
    get_settings,
    save_settings,
    get_provider_status,
    load_settings,
)
try:
    from .rag import RAGStore
except Exception as error:
    print(f"Could not import RAGStore: {error}")
    RAGStore = None  # type: ignore


class AnalyzeRequest(BaseModel):
    analysis_id: Optional[str] = None
    text: Optional[str] = None
    policy_id: Optional[str] = None
    policy: Optional[Dict[str, Any]] = None


class AnalyzeResponse(BaseModel):
    analysis_id: str
    total_clauses: int
    results: List[Dict[str, Any]]
    policy_summary: Optional[Dict[str, Any]] = None
    analysis_quality: Optional[Dict[str, Any]] = None


def orjson_dumps(v, *, default):
    return orjson.dumps(v, default=default).decode()


_DATE_RE_MAIN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Temporarily use default response class to debug startup issue
# app = FastAPI(default_response_class=ORJSONResponse)
app = FastAPI()

origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://[::1]:8080",
    "http://[::1]:5173",
    "http://[::1]:8081",
]

# Enable CORS so frontend (localhost:8080 / 5173) can fetch backend APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store()


def _persist_original_file(
    analysis_id: str,
    filename: str,
    content: bytes,
    content_type: Optional[str],
) -> None:
    """Save the raw uploaded file to disk and record its path, so the
    frontend can later render the real document instead of only our
    parsed text."""
    try:
        uploads_dir = UPLOADS_DIR
        os.makedirs(uploads_dir, exist_ok=True)

        _, ext = os.path.splitext(filename or "")
        stored_path = os.path.join(uploads_dir, f"{analysis_id}{ext}")

        with open(stored_path, "wb") as f:
            f.write(content)

        store.update_analysis(
            analysis_id,
            {"file_path": stored_path, "content_type": content_type},
        )
    except Exception as error:
        print(f"Failed to persist original file for {analysis_id}: {error}")
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploaded_files")

llm = LLMClient()
rag = None

# Chat search needs the embedding server at start-up. If it can't be
# reached then (a dropped connection, the shared server busy), search is
# tried again on the next upload, question or status check - at most
# every _RAG_RETRY_SEC - instead of staying off until the backend is
# restarted, with every contract uploaded meanwhile left unsearchable.
_RAG_RETRY_SEC = 30
_rag_init = {"last_attempt": 0.0, "error": None}
_rag_init_lock = threading.Lock()


def ensure_rag():
    """The search store, starting it if an earlier attempt failed."""
    global rag
    if rag is not None or RAGStore is None:
        return rag
    with _rag_init_lock:
        if rag is not None:
            return rag
        if time.time() - _rag_init["last_attempt"] < _RAG_RETRY_SEC:
            return None
        _rag_init["last_attempt"] = time.time()
        try:
            rag = RAGStore()
            _rag_init["error"] = None
            print("RAG system enabled")
        except Exception as error:
            _rag_init["error"] = str(error)
            print(f"RAG system failed to initialize (retrying in {_RAG_RETRY_SEC}s when needed): {error}")
    return rag


if RAGStore is not None:
    ensure_rag()
else:
    print(
        "RAGStore could not be imported. "
        "RAG system is disabled."
    )



def build_document(text: str, pages: List[str]) -> Dict[str, Any]:
    """
    Split extracted text into the contract header and its clauses, with
    page numbers, plus a check that nothing was silently dropped.
    """
    header_text, clause_texts = split_document(text)
    page_numbers = assign_clause_pages(
        ([header_text] if header_text else []) + clause_texts, pages or [text]
    )
    header = None
    if header_text:
        header = {"id": "header", "text": header_text, "page": page_numbers[0]}
        page_numbers = page_numbers[1:]

    clauses = [
        {
            "id": idx,
            "text": clause_text,
            "metadata": extract_metadata(clause_text),
            "page": page_numbers[idx - 1],
        }
        for idx, clause_text in enumerate(clause_texts, start=1)
    ]
    coverage = coverage_report(text, header_text, clause_texts)
    if not coverage["ok"]:
        print(
            f"[parse] only {coverage['ratio']:.0%} of the document's words ended up "
            f"in the header/clauses; e.g. missing: {coverage['missing_sample'][:8]}"
        )
    return {"header": header, "clauses": clauses, "parse_quality": coverage}


_ingest_lock = threading.Lock()


def ingest_document(
    filename: str,
    content: bytes,
    content_type: Optional[str],
    analysis_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse, extract and index one document.

    - New file: creates a record.
    - The same file uploaded again (same bytes), or a re-index: updates
      the existing record in place, so one document never becomes
      several records that all show up in search and chat.
    - If re-parsing changed the clauses, the old risk analysis no
      longer matches them and is cleared; the record goes back to
      "uploaded" and needs /analyze again.

    Blocking; routes call it through run_in_threadpool.
    Raises ValueError if no text could be extracted.
    """
    # Folder uploads can send "Folder/sub/file.pdf"; the contract's name
    # is the file name.
    filename = os.path.basename(str(filename or "").replace("\\", "/")) or "contract"
    text, ocr_info, pages = extract_text_from_file(filename, content)
    if not text or not text.strip():
        raise ValueError("No text could be extracted from the file")

    content_hash = hashlib.sha256(content).hexdigest()
    doc = build_document(text, pages)

    try:
        contract_metadata = llm.extract_contract_metadata(text, filename)
    except Exception as error:
        print(f"Contract metadata extraction failed for {filename}: {error}")
        contract_metadata = None

    fields = {
        "filename": filename,
        "header": doc["header"],
        "clauses": doc["clauses"],
        "parse_quality": doc["parse_quality"],
        "file_size": len(content),
        "ocr_info": ocr_info,
        "contract_metadata": contract_metadata,
        "content_hash": content_hash,
    }

    duplicate_of: Optional[str] = None
    with _ingest_lock:
        existing = store.get_analysis(analysis_id) if analysis_id else None
        if existing is None:
            existing = store.find_by_content_hash(content_hash)
            if existing is not None and existing.get("filename") and existing.get("filename") != filename:
                # The same file under another name (e.g. a copy in another
                # folder): keep the original record and its name.
                duplicate_of = existing.get("filename")
                fields["filename"] = duplicate_of
        reprocessed = existing is not None

        clauses_changed = True
        if reprocessed:
            analysis_id = existing["analysis_id"]
            old_texts = [c.get("text") for c in existing.get("clauses", [])]
            clauses_changed = old_texts != [c["text"] for c in doc["clauses"]]
            if clauses_changed:
                fields.update({
                    "status": "uploaded",
                    "results": None,
                    "policy_summary": None,
                    "summary": None,
                    "analysis_quality": None,
                })
            # If the AI server failed this time but an earlier extraction
            # by the model exists, keep that one: a pattern-only fallback
            # would otherwise wipe fields like the contract type or end
            # date that only the model can read.
            old_meta = existing.get("contract_metadata") or {}
            new_meta = contract_metadata or {}
            if new_meta.get("extraction_method") != "llm" and old_meta.get("extraction_method") == "llm":
                kept = dict(old_meta)
                kept["extraction_warnings"] = list(old_meta.get("extraction_warnings") or []) + [
                    "The AI server was unavailable when this file was re-processed; "
                    "the previous extraction was kept."
                ]
                fields["contract_metadata"] = kept
            store.update_analysis(analysis_id, fields)
        else:
            analysis_id = store.save_analysis({
                **fields,
                "status": "uploaded",
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            })

    _persist_original_file(analysis_id, filename, content, content_type)

    # Search index. A failure here means the chatbot can't find this
    # contract, so it's recorded on the contract and reported, not just
    # printed to the server log.
    search_index: Dict[str, Any] = {"ok": False, "passages": 0, "error": "Search is not available on this server."}
    if ensure_rag() is None and _rag_init["error"]:
        search_index["error"] = (
            "Could not add this contract to chat search: the embedding server couldn't be reached. "
            "Run a re-index once it's back."
        )
    if rag is not None:
        try:
            indexed = rag.index_analysis(analysis_id, doc["clauses"], doc["header"])
            search_index = {"ok": True, "passages": indexed, "error": None}
            print(f"Indexed {indexed} passages for analysis {analysis_id}")
        except Exception as error:
            print(f"RAG indexing failed for {analysis_id}: {error}")
            search_index = {"ok": False, "passages": 0, "error": f"Could not add this contract to chat search: {error}"}
    store.update_analysis(analysis_id, {"search_index": search_index})

    return {
        "analysis_id": analysis_id,
        "total_clauses": len(doc["clauses"]),
        "ocr_info": ocr_info,
        "reprocessed": reprocessed,
        "clauses_changed": clauses_changed,
        "parse_quality": doc["parse_quality"],
        "search_index": search_index,
        "duplicate_of": duplicate_of,
    }


# Old name, kept for anything that still imports it.
def _process_upload(filename, content, content_type):
    return ingest_document(filename, content, content_type)


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    # Only file.read() needs to happen on the event loop; everything
    # else is blocking work and runs on a worker thread instead
    # (see _process_upload's docstring for why).
    content = await file.read()
    try:
        result = await run_in_threadpool(
            _process_upload, file.filename, content, file.content_type
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


@app.post("/upload/batch")
async def batch_upload(files: TypingList[UploadFile] = File(...)):
    """Upload and process multiple contracts at once."""
    results = []
    errors = []
    
    for file in files:
        try:
            content = await file.read()
            processed = await run_in_threadpool(
                _process_upload, file.filename, content, file.content_type
            )
            results.append({
                "filename": file.filename,
                **processed,
            })
        except Exception as e:
            errors.append({"filename": file.filename, "error": str(e)})
    
    return {
        "success_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors
    }


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest):
    # determine source text
    if payload.analysis_id:
        record = store.get_analysis(payload.analysis_id)
        if not record:
            raise HTTPException(status_code=404, detail="analysis_id not found")
        clauses = record.get("clauses", [])
    elif payload.text:
        doc = build_document(payload.text, [payload.text])
        clauses = doc["clauses"]
        record = {"header": doc["header"]}
        # persist a transient analysis
        analysis_id = store.save_analysis({
            "filename": None,
            "header": doc["header"],
            "parse_quality": doc["parse_quality"],
            "clauses": clauses,
            "status": "uploaded",
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "file_size": None,
        })
        payload.analysis_id = analysis_id
    else:
        raise HTTPException(status_code=400, detail="Provide either analysis_id or text")
    
    # If no policy specified, create and apply a comprehensive default policy
    if not payload.policy and not payload.policy_id:
        # Create default policy that covers all domains
        default_policy = {
            "policy_id": "default_comprehensive",
            "name": "Default Comprehensive Policy",
            "risk_threshold": 50,
            "domains": [
                {
                    "domain_name": "Financial",
                    "micro_policies": [
                        {"id": "fin_payment", "name": "Payment Terms", "check": "payment terms 30 days net invoice", "risk_weight": 5},
                        {"id": "fin_late", "name": "Late Fees", "check": "late fee penalty delay payment", "risk_weight": 3}
                    ]
                },
                {
                    "domain_name": "Legal",
                    "micro_policies": [
                        {"id": "legal_liability", "name": "Liability Cap", "check": "liability cap limit exceed", "risk_weight": 8},
                        {"id": "legal_indemnify", "name": "Indemnification", "check": "indemnify indemnification hold harmless", "risk_weight": 10},
                        {"id": "legal_governing", "name": "Governing Law", "check": "governing law jurisdiction", "risk_weight": 4}
                    ]
                },
                {
                    "domain_name": "Operational",
                    "micro_policies": [
                        {"id": "op_term", "name": "Termination Terms", "check": "termination notice period", "risk_weight": 6},
                        {"id": "op_sla", "name": "SLA Requirements", "check": "uptime availability sla service level", "risk_weight": 5}
                    ]
                },
                {
                    "domain_name": "Privacy",
                    "micro_policies": [
                        {"id": "priv_data", "name": "Data Protection", "check": "data protection privacy gdpr personal", "risk_weight": 9},
                        {"id": "priv_conf", "name": "Confidentiality", "check": "confidential confidentiality nda", "risk_weight": 7}
                    ]
                },
                {
                    "domain_name": "Security",
                    "micro_policies": [
                        {"id": "sec_breach", "name": "Security Breach", "check": "security breach incident notification", "risk_weight": 10},
                        {"id": "sec_encrypt", "name": "Encryption", "check": "encryption secure data protection", "risk_weight": 6}
                    ]
                },
                {
                    "domain_name": "Intellectual Property",
                    "micro_policies": [
                        {"id": "ip_ownership", "name": "IP Ownership", "check": "intellectual property ownership rights", "risk_weight": 8},
                        {"id": "ip_license", "name": "License Terms", "check": "license grant perpetual transferable", "risk_weight": 5}
                    ]
                }
            ]
        }
        payload.policy = default_policy

    def _make_title(text: str, cls: Dict[str, Any]) -> str:
        import re
        t = (text or "").strip()
        # Extract first 2-3 significant words from the clause text
        tokens = re.findall(r"[A-Za-z0-9]+", t)
        words = [w.capitalize() for w in tokens[:3]]
        title = " ".join(words) if words else (cls.get("domain") or "Clause")
        return title

    results: List[Dict[str, Any]] = []

    def _classify_one(c: Dict[str, Any]) -> Dict[str, Any]:
        ctx = None
        if rag is not None:
            try:
                # Retrieve similar clauses (cross-analysis). Tune top_k via env if needed.
                ctx = rag.query(c.get("text", ""), top_k=5)
            except Exception:
                ctx = None
        classification = llm.classify_clause(c["text"], c.get("metadata", {}), context=ctx)
        return {
            **c,
            "classification": classification,
            "title": _make_title(c.get("text", ""), classification or {}),
        }

    # Each clause's classification is an independent LLM call, so fire
    # them concurrently instead of one at a time - this is what was
    # making /analyze take minutes on a slow remote model (see
    # llm_concurrency's comment for the tradeoff this involves).
    concurrency = max(1, int(get_settings().get("llm_concurrency", 4)))
    if len(clauses) <= 1 or concurrency <= 1:
        for c in clauses:
            results.append(_classify_one(c))
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            # map() preserves input order in its output order, even
            # though the underlying calls complete out of order.
            results = list(executor.map(_classify_one, clauses))

    # optional policy evaluation
    policy_summary = None
    policy_obj: Optional[Dict[str, Any]] = None
    if payload.policy:
        policy_obj = payload.policy
    elif payload.policy_id:
        policy_obj = get_policy(payload.policy_id)
        if policy_obj is None:
            raise HTTPException(status_code=404, detail="policy_id not found")

    # Classifications that fell back to keyword guessing (the model call
    # failed even after its retries) get one more try, in parallel; the
    # shared server has often recovered by the end of the batch. If most
    # clauses failed, the server is down: don't wait on it again - the
    # analysis is recorded as incomplete instead.
    failed = [
        i for i, r in enumerate(results)
        if (r.get("classification") or {}).get("method") == "keyword_fallback"
    ]
    if failed and len(failed) <= len(results) / 2:
        retry_inputs = [
            {k: v for k, v in results[i].items() if k not in ("classification", "title")} for i in failed
        ]
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for i, retried in zip(failed, executor.map(_classify_one, retry_inputs)):
                results[i] = retried

    if policy_obj:
        enriched, summary = apply_policy(results, policy_obj, llm=llm)
        results = enriched
        policy_summary = summary

    analysis_quality = _analysis_quality(results, policy_summary)

    # update store
    update_payload: Dict[str, Any] = {
        "status": "analyzed",
        "results": results,
        "analysis_quality": analysis_quality,
        # Stored so a later re-index can re-run the exact same policy
        # (the app builds its policy in the browser; the backend can't
        # reconstruct it).
        "policy_used": policy_obj,
    }
    if policy_summary:
        update_payload["policy_summary"] = policy_summary

    # Automatically generate the executive summary now, since this is
    # the first point where clauses have risk classifications attached
    # (generate_contract_summary counts high/medium/low risk clauses -
    # doing this at /upload instead would always report 0 high-risk
    # clauses, since classification hasn't run yet at that point).
    # The header (parties, amounts) gives the summary its context;
    # it's included as text only, never as a scored clause.
    header_text = ((record or {}).get("header") or {}).get("text", "")
    contract_text = " ".join(
        ([header_text] if header_text else []) + [c.get("text", "") for c in results]
    )
    try:
        executive_summary = llm.generate_contract_summary(contract_text, results)
    except Exception as error:
        print(f"Automatic summary generation failed for {payload.analysis_id}: {error}")
        executive_summary = None

    # A failed summary must not leave the previous one (with old risk
    # counts) next to the new results.
    update_payload["summary"] = executive_summary or None

    store.update_analysis(payload.analysis_id, update_payload)

    return AnalyzeResponse(
        analysis_id=payload.analysis_id,
        total_clauses=len(results),
        results=results,
        policy_summary=policy_summary,
        analysis_quality=analysis_quality,
    )


def _analysis_quality(results: List[Dict[str, Any]], policy_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Whether the model actually did the analysis. When the AI server
    fails, clauses are classified by keyword matching instead, which is
    much less accurate - most clauses come out "Low" risk. That used to
    be saved as a normal analysis with nothing to show for it.
    """
    fallback_clauses = [
        r.get("id") for r in results
        if (r.get("classification") or {}).get("method") == "keyword_fallback"
    ]
    fallback_checks = int((policy_summary or {}).get("keyword_fallback_checks") or 0)
    total_checks = int((policy_summary or {}).get("total_checks") or 0)
    complete = not fallback_clauses and not fallback_checks
    message = None
    if not complete:
        parts = []
        if fallback_clauses:
            parts.append(f"{len(fallback_clauses)} of {len(results)} clauses")
        if fallback_checks:
            parts.append(f"{fallback_checks} of {total_checks} policy checks")
        message = (
            "The AI server didn't respond for " + " and ".join(parts) + ", so they were scored by "
            "keyword matching, which is much less reliable. Re-run the analysis when the server is available."
        )
    return {
        "complete": complete,
        "fallback_clauses": fallback_clauses,
        "fallback_policy_checks": fallback_checks,
        "message": message,
    }


@app.get("/rag/status")
def rag_status():
    if ensure_rag() is None:
        return {"enabled": False, "error": _rag_init["error"]}
    try:
        info = rag.client.get_collection(rag.collection)
        return {
            "enabled": True,
            "collection": rag.collection,
            "vectors_count": getattr(info, "points_count", None) or getattr(info, "vectors_count", None),
            "status": getattr(info, "status", None),
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}


@app.get("/clauses")
def list_analyses():
    return store.list_analyses()


@app.get("/clauses/{analysis_id}")
def get_analysis(analysis_id: str):
    data = store.get_analysis(analysis_id)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return data

@app.get("/clauses/{analysis_id}/file")
def get_analysis_file(analysis_id: str):
    data = store.get_analysis(analysis_id)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")

    file_path = data.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Original file not available for this analysis",
        )

    return FileResponse(
        path=file_path,
        media_type=data.get("content_type") or "application/pdf",
        filename=data.get("filename") or os.path.basename(file_path),
    )

@app.get("/")
def root():
    return {"status": "ok"}


# --- Policy management endpoints ---

@app.post("/policy")
def upsert_policy(policy: Dict[str, Any] = Body(...)):
    try:
        pid = save_policy(policy)
        return {"policy_id": pid, "status": "saved"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@app.get("/policy/{policy_id}")
def get_policy_endpoint(policy_id: str):
    p = get_policy(policy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p


@app.get("/policies")
def list_policies_endpoint():
    return list_policies()


@app.post("/recommend")
def generate_recommendation(payload: Dict[str, Any] = Body(...)):
    """Generate alternative wording recommendation for a high-risk clause."""
    text = payload.get("text", "")
    risk_level = payload.get("risk_level", "")
    reasons = payload.get("reasons", [])
    
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    
    recommendation = llm.generate_recommendation(text, risk_level, reasons)
    
    if recommendation:
        return {"recommendation": recommendation}
    else:
        return {"recommendation": None, "message": "Could not generate recommendation"}


@app.post("/summary/{analysis_id}")
def generate_summary(analysis_id: str):
    """Generate AI-powered executive summary for a contract."""
    analysis = store.get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    clauses = analysis.get("results") or analysis.get("clauses") or []
    contract_text = " ".join([c.get("text", "") for c in clauses])
    
    summary = llm.generate_contract_summary(contract_text, clauses)
    
    if summary:
        # Store summary in analysis
        store.update_analysis(analysis_id, {"summary": summary})
        return summary
    else:
        raise HTTPException(status_code=500, detail="Could not generate summary")


@app.get("/contracts")
def list_contracts(include_expired: bool = True):
    """
    Return the contract directory (filename + extracted metadata) for
    every stored analysis. Powers listing/filtering UI and is the same
    data the /chat endpoint feeds to the assistant.
    """
    from datetime import date as _date

    analyses = store.list_analyses()
    contracts = []
    today = _date.today().isoformat()

    for a in analyses:
        cm = a.get("contract_metadata") or {}
        end_date = cm.get("end_date")
        is_expired = bool(end_date and _DATE_RE_MAIN.match(end_date or "") and end_date < today)

        if not include_expired and is_expired:
            continue

        contracts.append({
            "analysis_id": a.get("analysis_id"),
            "filename": a.get("filename"),
            "customer_name": cm.get("customer_name"),
            "lender_name": cm.get("lender_name"),
            "contract_about": cm.get("contract_about"),
            "start_date": cm.get("start_date"),
            "end_date": cm.get("end_date"),
            "contract_value": cm.get("contract_value"),
            "currency": cm.get("currency"),
            "ip_shared_with_customer": cm.get("ip_shared_with_customer"),
            "indemnification_clause_present": cm.get("indemnification_clause_present"),
            "indemnification_strength": cm.get("indemnification_strength"),
            "governing_law": cm.get("governing_law"),
            "is_expired": is_expired,
            "has_metadata": bool(cm),
        })

    return {"contracts": contracts}


@app.post("/contracts/backfill-metadata")
def backfill_contract_metadata(force: bool = False):
    """
    Extract contract_metadata for analyses that were uploaded before
    this feature existed (or, with force=true, re-extract for all
    analyses). Needed because existing entries in the store only have
    an analysis_id and filename, which isn't enough to answer
    listing/filtering questions correctly.
    """
    analyses = store.list_analyses()
    updated = []
    skipped = []
    failed = []

    def _backfill_one(a: Dict[str, Any]):
        analysis_id = a.get("analysis_id")

        # Prefer re-parsing the original stored file over joined clause
        # text: clause splitting deliberately drops the preamble (where
        # party/lender names normally live, e.g. "between Bank Of
        # America Inc. (the "BANK") and ..."), so contracts analyzed
        # before lender_name existed can only pick it up by going back
        # to the source PDF, not from what's already stored as clauses.
        contract_text = ""
        file_path = a.get("file_path")
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    raw_bytes = f.read()
                contract_text, _ocr_info, _pages = extract_text_from_file(
                    a.get("filename") or os.path.basename(file_path),
                    raw_bytes,
                )
                contract_text = (contract_text or "").strip()
            except Exception as error:
                print(
                    f"Could not re-parse original file for {analysis_id}, "
                    f"falling back to stored clause text: {error}"
                )

        if not contract_text:
            clauses = a.get("results") or a.get("clauses") or []
            contract_text = " ".join(c.get("text", "") for c in clauses).strip()

        if not contract_text:
            return ("failed", analysis_id, "No clause text stored for this analysis")

        try:
            contract_metadata = llm.extract_contract_metadata(contract_text, a.get("filename"))
            old_meta = a.get("contract_metadata") or {}
            if contract_metadata.get("extraction_method") != "llm" and old_meta.get("extraction_method") == "llm":
                # AI server failed this time: don't replace a model
                # extraction with a pattern-only one.
                return ("failed", analysis_id, "The AI server didn't respond; kept the existing extraction.")
            store.update_analysis(analysis_id, {"contract_metadata": contract_metadata})
            return ("updated", analysis_id, None)
        except Exception as error:
            return ("failed", analysis_id, str(error))

    to_process = []
    for a in analyses:
        analysis_id = a.get("analysis_id")
        if not force and a.get("contract_metadata"):
            skipped.append(analysis_id)
            continue
        to_process.append(a)

    # Each contract's metadata extraction is an independent LLM call -
    # this loop used to run them one at a time, which is why a
    # force=true backfill across every stored contract could sit for
    # minutes with zero visible progress in the HTTP response. Fire
    # them concurrently instead, same as /analyze's per-clause loop.
    try:
        concurrency = max(1, int(get_settings().get("llm_concurrency", 4)))
    except Exception:
        concurrency = 4

    if len(to_process) <= 1 or concurrency <= 1:
        outcomes = [_backfill_one(a) for a in to_process]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            outcomes = list(executor.map(_backfill_one, to_process))

    for status, analysis_id, error in outcomes:
        if status == "updated":
            updated.append(analysis_id)
        else:
            failed.append({"analysis_id": analysis_id, "error": error})

    return {
        "updated": updated,
        "skipped_already_had_metadata": skipped,
        "failed": failed,
    }


# --- One-time / on-demand re-index ------------------------------------

_reindex_state: Dict[str, Any] = {"running": False}
_reindex_lock = threading.Lock()


def _file_bytes(record: Dict[str, Any]) -> Optional[bytes]:
    path = record.get("file_path")
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _run_reindex(reanalyze: str, remove_duplicates: bool, reset_index: bool) -> None:
    state = _reindex_state
    try:
        analyses = store.list_analyses()  # newest first
        state.update({"total": len(analyses), "done": 0, "phase": "checking duplicates"})

        # Duplicates: same file bytes stored more than once.
        by_hash: Dict[str, List[Dict[str, Any]]] = {}
        for a in analyses:
            content = _file_bytes(a)
            h = a.get("content_hash") or (hashlib.sha256(content).hexdigest() if content else None)
            if h:
                by_hash.setdefault(h, []).append(a)
        duplicate_groups = [g for g in by_hash.values() if len(g) > 1]
        removed = []
        for group in duplicate_groups:
            keep, extras = group[0], group[1:]
            state["duplicates"].append({
                "kept": {"analysis_id": keep["analysis_id"], "filename": keep.get("filename")},
                "extra_copies": [{"analysis_id": e["analysis_id"], "filename": e.get("filename")} for e in extras],
            })
            if remove_duplicates:
                for e in extras:
                    store.delete_analysis(e["analysis_id"])
                    if rag is not None:
                        rag.delete_analysis(e["analysis_id"])
                    removed.append(e["analysis_id"])
        state["removed_duplicates"] = removed
        analyses = [a for a in analyses if a["analysis_id"] not in set(removed)]
        state["total"] = len(analyses)

        if ensure_rag() is None:
            state["search_warning"] = (
                "Chat search is not available (" + str(_rag_init["error"] or "embedding server unreachable")[:200]
                + "); contracts are re-parsed but not added to search."
            )
        if reset_index and rag is not None:
            state["phase"] = "resetting search index"
            rag.reset()

        state["phase"] = "re-parsing, extracting and indexing"

        def _one(a: Dict[str, Any]) -> Dict[str, Any]:
            aid = a["analysis_id"]
            try:
                content = _file_bytes(a)
                if content is not None:
                    info = ingest_document(a.get("filename") or aid, content, a.get("content_type"), analysis_id=aid)
                    changed = info["clauses_changed"]
                    if not info["search_index"]["ok"]:
                        # Parsed and stored fine (so it still gets re-analyzed),
                        # but the chatbot can't find it until this is fixed.
                        return {"analysis_id": aid, "filename": a.get("filename"), "ok": True,
                                "clauses_changed": changed, "search_ok": False,
                                "warning": info["search_index"]["error"]}
                else:
                    # No original file (text submissions): keep clauses,
                    # re-index what's stored.
                    if rag is not None:
                        rag.index_analysis(aid, a.get("clauses", []), a.get("header"))
                    changed = False
                return {"analysis_id": aid, "filename": a.get("filename"), "ok": True, "clauses_changed": changed}
            except Exception as error:
                return {"analysis_id": aid, "filename": a.get("filename"), "ok": False, "error": str(error)}
            finally:
                state["done"] = state.get("done", 0) + 1

        concurrency = max(1, int(get_settings().get("llm_concurrency", 4)))
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            outcomes = list(ex.map(_one, analyses))
        state["results"] = outcomes
        state["not_searchable"] = [o["filename"] or o["analysis_id"] for o in outcomes if o.get("search_ok") is False]

        # Re-run risk analysis where needed, with the policy each
        # contract was originally analyzed with.
        state["phase"] = "re-analyzing"
        to_analyze = []
        for o in outcomes:
            if not o["ok"]:
                continue
            record = store.get_analysis(o["analysis_id"]) or {}
            needs = (
                reanalyze == "all"
                or (reanalyze == "changed" and (o["clauses_changed"] or record.get("status") != "analyzed"))
            )
            if not needs:
                continue
            if record.get("policy_used"):
                to_analyze.append(record)
            # Analyzed before policies were stored (or never analyzed):
            # the app's policy isn't known here. Re-uploading the same
            # file in the app refreshes this record and analyzes it.
            else:
                state["needs_analysis"].append({"analysis_id": record.get("analysis_id"), "filename": record.get("filename")})

        state.update({"total": len(to_analyze), "done": 0})
        for record in to_analyze:
            try:
                analyze(AnalyzeRequest(analysis_id=record["analysis_id"], policy=record["policy_used"]))
                state["reanalyzed"].append(record.get("filename"))
            except Exception as error:
                state["errors"].append({"filename": record.get("filename"), "error": str(error)})
            state["done"] += 1

        state["phase"] = "finished"
    except Exception as error:
        state["phase"] = "failed"
        state["errors"].append({"error": str(error)})
    finally:
        state["running"] = False
        state["finished_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"


@app.post("/admin/reindex")
def start_reindex(
    reanalyze: str = "changed",
    remove_duplicates: bool = False,
    reset_index: bool = True,
):
    """
    Rebuild every stored contract with the current parser, metadata
    extraction and search index. Runs in the background; poll
    GET /admin/reindex/status.

    reanalyze: "changed" (default) re-runs risk analysis only where the
      clauses came out different; "all"; or "none".
    remove_duplicates: delete extra copies of files uploaded more than
      once (keeps the newest). Default false: only reported.
    reset_index: rebuild the search index from scratch (default true).
    """
    if reanalyze not in {"changed", "all", "none"}:
        raise HTTPException(status_code=400, detail="reanalyze must be changed, all or none")
    with _reindex_lock:
        if _reindex_state.get("running"):
            return {"started": False, "message": "A re-index is already running", "status": _reindex_state}
        _reindex_state.clear()
        _reindex_state.update({
            "running": True,
            "started_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "phase": "starting",
            "done": 0,
            "total": 0,
            "duplicates": [],
            "removed_duplicates": [],
            "results": [],
            "reanalyzed": [],
            "needs_analysis": [],
            "not_searchable": [],
            "errors": [],
        })
        threading.Thread(
            target=_run_reindex, args=(reanalyze, remove_duplicates, reset_index), daemon=True
        ).start()
    return {"started": True, "message": "Re-index started. Poll GET /admin/reindex/status."}


@app.get("/admin/reindex/status")
def reindex_status():
    return _reindex_state


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    analysis_id: Optional[str] = None
    top_k: int = 5
    # Recent turns of this conversation, oldest first, so follow-ups
    # ("and the lowest?", "that's wrong, check again") make sense.
    history: List[ChatTurn] = []
    # The query behind the previous answer when it was computed exactly,
    # so "list the other ones too" can widen it.
    previous_spec: Optional[Dict[str, Any]] = None
    # The contracts that answer showed, so "the other ones" leaves them out.
    previous_ids: List[str] = []


def _directory_line(a: Dict[str, Any]) -> str:
    from .chat_router import format_money

    cm = a.get("contract_metadata") or {}

    def _fmt(value):
        if isinstance(value, bool):
            return "yes" if value else "no"
        return value if value not in (None, "") else "not found"

    value = cm.get("contract_value")
    value_display = (
        format_money(float(value), cm.get("currency"))
        if isinstance(value, (int, float)) else "not found"
    )
    fields = [
        f"ID: {a.get('analysis_id')}",
        f"Name: {a.get('filename') or 'Contract ' + str(a.get('analysis_id'))}",
        f"Borrower/customer: {_fmt(cm.get('customer_name'))}",
        f"Lender: {_fmt(cm.get('lender_name'))}",
        f"About: {_fmt(cm.get('contract_about'))}",
        f"Start: {_fmt(cm.get('start_date'))}",
        f"End: {_fmt(cm.get('end_date'))}",
        f"Amount: {value_display}",
        f"Governing law: {_fmt(cm.get('governing_law'))}",
        f"Indemnification clause: {_fmt(cm.get('indemnification_clause_present'))}",
    ]
    results = a.get("results") or []
    if a.get("status") == "analyzed" and results:
        levels = [str((r.get("classification") or {}).get("risk_level", "")).lower() for r in results]
        fields.append(
            f"Risk analysis: {levels.count('high')} high / {levels.count('medium')} medium / "
            f"{levels.count('low')} low-risk clauses of {len(results)}"
        )
    else:
        fields.append("Risk analysis: not analyzed yet")
    return "- " + " | ".join(fields)


# Whole-contract context is used when chatting about one contract and it
# fits; retrieval only picks a few passages, the whole text can't miss one.
_SINGLE_CONTRACT_CHAR_BUDGET = 16000

CHAT_SYSTEM_PROMPT = """
You are a contract analysis assistant for legal review. You answer questions
about the contracts provided, compare terms, assess risk and draft wording.

You have no tools and cannot call any. Answer only from the directory and the
numbered sources in the prompt.

Rules:
1. Every fact you state (name, amount, date, rate, term) must come from the
   sources or the directory. Cite the source it came from exactly as
   [Source N](#source-N), e.g. [Source 2](#source-2) - not [2], (Source 2)
   or the source's whole label.
   If something isn't in them, say it isn't in the provided documents. Never
   guess or fill in a value.
2. Do not compute rankings, totals or comparisons of amounts in your head; if
   asked, describe what the sources say and note that exact ranking is
   available by asking directly (e.g. "which contract has the highest amount").
3. If the conversation shows an earlier answer was wrong or inconsistent, say so
   plainly and give the correct answer from the sources.
4. For yes/no questions, start with Yes / No / Partially / It depends, then one
   or two sentences of reasoning.
5. When listing contracts, use a Markdown table and a link column with
   [View](#contract-<ID>) using the directory ID. Never show the ID itself
   as text or as its own column; it is only for that link.
6. When drafting clause wording, put the draft in a blockquote, separate from
   your explanation.
7. Be concise. Don't repeat caveats.
8. A contract's risk comes only from its risk analysis (the directory's
   high / medium / low-risk clause counts and the clause wording). Never
   infer risk from the amount, the lender or anything else, and never state
   a general rule (e.g. "larger loans are riskier") that isn't in the sources.
9. Refer to a clause only by the clause shown in its source's label, and
   state a value only if that source's text contains it. Never move a
   number from one clause, rate or contract to another.
10. A source marked "identical wording also in: ..." applies to every
   contract listed; say so instead of repeating it per contract.
11. When a contract states several values of one kind (e.g. a regular
   interest rate and a late-payment interest rate, or a penalty and an
   interest), list each with what it is for and its clause.
12. If asked whether a term is fine, acceptable, reasonable or compliant,
   and no policy or standard in the sources defines what is acceptable,
   state the term(s) exactly and say there is no defined standard to judge
   them against. Do not approve or reject them on your own.
13. If the user says an earlier answer was wrong, re-check against the
   sources only; don't defend or repeat the earlier answer.
""".strip()


def _history_block(history: List[Dict[str, str]]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-6:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {str(turn.get('content', ''))[:1500]}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


# Total characters of clause text sent with one question when it has to
# look across many contracts (one passage per contract, shortened to fit).
_ACROSS_CHAR_BUDGET = 20000
_MAX_NAMED_CONTRACTS = 6


# Upper bound for the whole chat prompt, in characters (~3.5 characters
# per token): leaves room in ollama_num_ctx (16384 tokens) for the system
# prompt and the answer.
_MAX_PROMPT_CHARS = 40000

_FOCUS_STOPWORDS = {
    "the", "and", "for", "are", "what", "which", "does", "with", "this", "that", "from", "have",
    "has", "any", "all", "contract", "contracts", "clause", "clauses", "say", "says", "about",
    "more", "than", "less", "how", "much", "many", "there", "their", "they", "who", "when",
}


def _focus_passage(text: str, question: str, limit: int) -> str:
    """
    Shorten a passage to about `limit` characters around the sentences
    that share the most words with the question, instead of keeping just
    its opening - a rate or amount stated late in a clause survives.
    """
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    words = {w.strip(".") for w in re.findall(r"[a-z0-9%.]{3,}", question.lower())}
    words = {w for w in words if w and w not in _FOCUS_STOPWORDS}
    patterns = [re.compile(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])") for w in words]

    def score(chunk: str) -> int:
        low = chunk.lower()
        return sum(1 for p in patterns if p.search(low))

    sentences = re.split(r"(?<=[.;:])\s+", text)
    if len(sentences) == 1:
        # One long sentence: take the window around the best-matching
        # words instead of its opening.
        low = text.lower()
        hits = [(m.start(), i) for i, p in enumerate(patterns) for m in p.finditer(low)]
        if not hits:
            return text[:limit].rsplit(" ", 1)[0] + " …"
        # Centre on the spot where the most distinct question words meet,
        # rare ones counting more ("1.4%" once beats "monthly" five times).
        counts: Dict[int, int] = {}
        for _, i in hits:
            counts[i] = counts.get(i, 0) + 1
        half = limit // 2

        def window_score(pos: int) -> float:
            near = {i for p2, i in hits if abs(p2 - pos) <= half}
            return sum(1.0 / counts[i] for i in near)

        centre = max((p2 for p2, _ in hits), key=window_score)
        start = max(0, min(centre - limit // 2, len(text) - limit))
        window = text[start:start + limit]
        if start > 0:
            window = window.split(" ", 1)[-1]
        if start + limit < len(text):
            window = window.rsplit(" ", 1)[0]
        return ("… " if start > 0 else "") + window + (" …" if start + limit < len(text) else "")
    scores = [score(s) for s in sentences]
    best = max(range(len(sentences)), key=lambda i: (scores[i], -i))
    lo = hi = best
    size = len(sentences[best])
    while True:
        grew = False
        for j in (hi + 1, lo - 1):
            if 0 <= j < len(sentences) and not (lo <= j <= hi) and size + len(sentences[j]) + 1 <= limit:
                size += len(sentences[j]) + 1
                lo, hi = min(lo, j), max(hi, j)
                grew = True
        if not grew:
            break
    out = " ".join(sentences[lo:hi + 1])
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0]
    return ("… " if lo > 0 else "") + out + (" …" if hi < len(sentences) - 1 or len(out) < len(" ".join(sentences[lo:hi + 1])) else "")


def _whole_contract_passages(record: Dict[str, Any], budget: int) -> Optional[List[Dict[str, Any]]]:
    """Header + every clause of one contract, or None if it doesn't fit."""
    header = record.get("header") or {}
    clauses = record.get("clauses") or []
    total = len(header.get("text") or "") + sum(len(c.get("text") or "") for c in clauses)
    if total > budget:
        return None
    aid = record.get("analysis_id")
    out: List[Dict[str, Any]] = []
    if header.get("text"):
        out.append({"analysis_id": aid, "clause_id": "header", "kind": "header", "text": header["text"], "score": None})
    out.extend(
        {"analysis_id": aid, "clause_id": c.get("id"), "kind": "clause", "text": c.get("text", ""), "score": None}
        for c in clauses
    )
    return out


_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_NUM = r"(?:\d{1,3}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_CLAUSE_REF = re.compile(
    r"\b(?:clauses?|articles?|sections?|§)\s*(" + _NUM + r"(?:\s*(?:,|and|&|or|/)\s*" + _NUM + r")*)",
    re.IGNORECASE,
)


def _clause_numbers(text: str) -> List[int]:
    """Clause numbers the question refers to: "clauses 3 and 6",
    "clause six", "section 2, 4"."""
    found: List[int] = []
    for m in _CLAUSE_REF.finditer(text or ""):
        for tok in re.findall(_NUM, m.group(1), re.IGNORECASE):
            n = int(tok) if tok.isdigit() else _NUMBER_WORDS.get(tok.lower())
            if n and n not in found:
                found.append(n)
    return found[:6]


def _clause_by_number(record: Dict[str, Any], n: int) -> Optional[Dict[str, Any]]:
    """The clause headed "CLAUSE SIX" / "Clause 6" / "6." in this contract,
    else the clause stored as number n."""
    word = [w for w, i in _NUMBER_WORDS.items() if i == n]
    heading = re.compile(
        r"^\s*(?:(?:clause|article|section)\s+(?:" + str(n) + (("|" + word[0]) if word else "") + r")\b|" + str(n) + r"[.)]\s)",
        re.IGNORECASE,
    )
    clauses = record.get("clauses") or []
    for c in clauses:
        if heading.match(str(c.get("text", ""))):
            return c
    for c in clauses:
        if str(c.get("id")) == str(n):
            return c
    return None


def _merge_identical(passages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Many contracts are the same template: the same clause wording appears
    in each of them. Sending 17 copies of one sentence wastes the prompt
    and invites the model to mix them up, so identical wording becomes
    one source that lists every contract it appears in.
    """
    merged: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for p in passages:
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text).lower()
        if key in by_key:
            first = by_key[key]
            if p.get("analysis_id") != first.get("analysis_id") and p.get("analysis_id") not in first["also_in"]:
                first["also_in"].append(p.get("analysis_id"))
            continue
        entry = dict(p, text=text, also_in=[])
        by_key[key] = entry
        merged.append(entry)
    return merged


def _answer_with_fallback(prompt: str):
    """
    Write the chat answer with the first model that can: the configured
    chat model, then its fallbacks (settings: ollama_chat_model,
    ollama_chat_fallback_models, then ollama_quality_model). A bigger
    model that doesn't fit in the shared server's memory right now hands
    over to the next one instead of failing the question.
    Returns (reply, model, failures) - reply None if every model failed.
    """
    from .llm_providers import chat_models

    if get_settings().get("provider", "ollama") != "ollama":
        provider = llm._get_provider("quality")
        try:
            return provider.invoke(prompt, system=CHAT_SYSTEM_PROMPT, temperature=0), getattr(provider, "model", None), []
        except Exception as error:
            return None, None, [str(error)]

    failures: List[str] = []
    for model in chat_models():
        try:
            reply = llm._provider_for_model(model).invoke(prompt, system=CHAT_SYSTEM_PROMPT, temperature=0)
            if failures:
                print(f"[chat] fell back to {model} after: {' | '.join(failures)}")
            return reply, model, failures
        except Exception as error:
            failures.append(f"{model}: {str(error)[:160]}")
    return None, None, failures


def _cited_source_numbers(reply: str) -> List[int]:
    found = re.findall(r"#source-(\d+)|\[Source (\d+)\]", reply or "")
    return sorted({int(a or b) for a, b in found})


# How the model actually cites, besides the asked-for [Source 2](#source-2):
# "[Source 2]", the whole label it was shown "[Source 2 | file.pdf | clause
# 3]", "(Source 2)", "[Sources 1, 3]", "(Sources 1 and 2)", "[2]". Left as
# they were, none of these was a link and the source list came back empty.
_CITE_NUMS = r"\d+(?:\s*(?:,|;|&|and|to|-|\u2013)\s*(?:Sources?\s*)?\d+)*"
_CITE_LINKED = re.compile(r"\[Sources?\s*(\d+)\]\(#source-(\d+)\)", re.I)
# A copied label can hold parentheses ("contract header (parties,
# amounts)"), so square brackets allow them inside; round ones don't.
_CITE_BRACKETED = re.compile(
    r"(?P<open>\[)\s*Sources?\s*(?P<nums>" + _CITE_NUMS + r")[^\[\]\n]{0,200}\](?!\()"
    r"|(?P<open2>\()\s*Sources?\s*(?P<nums2>" + _CITE_NUMS + r")[^()\n]{0,120}\)"
    r"|(?P<open3>\u3010)\s*Sources?\s*(?P<nums3>" + _CITE_NUMS + r")[^\u3010\u3011\n]{0,200}\u3011",
    re.I,
)
_CITE_NUMERIC = re.compile(r"\[(?P<nums>\d+(?:\s*,\s*\d+)*)\](?![(:])")
_CITE_BARE = re.compile(r"(?<![\[\w#-])Sources?\s+(?P<nums>" + _CITE_NUMS + r")\b(?![\]\w])")


def _expand_cited(nums: str) -> List[int]:
    out: List[int] = []
    for part in re.split(r"\s*(?:,|;|&|\band\b)\s*", re.sub(r"(?i)sources?", "", nums)):
        m = re.fullmatch(r"(\d+)\s*(?:-|\u2013|to)\s*(\d+)", part.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a < 20:
                out.extend(range(a, b + 1))
                continue
        out.extend(int(n) for n in re.findall(r"\d+", part))
    return out


def link_citations(reply: str, source_count: int) -> str:
    """Every way the model cites a source, turned into [Source N](#source-N)
    links; numbers with no such source are left as plain text."""
    if not reply or source_count <= 0:
        return reply

    def links(numbers: List[int]) -> Optional[str]:
        valid = [n for n in dict.fromkeys(numbers) if 1 <= n <= source_count]
        if not valid:
            return None
        return ", ".join(f"[Source {n}](#source-{n})" for n in valid)

    def fix_linked(m: "re.Match") -> str:
        n = int(m.group(2))
        return f"[Source {n}](#source-{n})" if 1 <= n <= source_count else f"Source {n}"

    def fix_bracketed(m: "re.Match") -> str:
        numbers = _expand_cited(m.group("nums") or m.group("nums2") or m.group("nums3"))
        linked = links(numbers)
        if linked is None:
            return "Source " + ", ".join(str(n) for n in numbers)
        return f"({linked})" if m.group("open2") else linked

    def fix_numeric(m: "re.Match") -> str:
        numbers = [int(n) for n in re.findall(r"\d+", m.group("nums"))]
        if not all(1 <= n <= source_count for n in numbers):
            return m.group(0)
        return links(numbers) or m.group(0)

    def fix_bare(m: "re.Match") -> str:
        numbers = _expand_cited(m.group("nums"))
        if all(1 <= n <= source_count for n in numbers):
            return links(numbers) or m.group(0)
        # "Per Source 3, 60 months": only the first number is a source;
        # the rest of the sentence stays as written.
        first = re.match(r"Sources?\s+(\d+)", m.group(0))
        n = int(first.group(1))
        if not 1 <= n <= source_count:
            return m.group(0)
        return f"[Source {n}](#source-{n})" + m.group(0)[first.end():]

    # Code blocks (a drafted clause, a table in a fence) are left alone.
    pieces = re.split(r"(```.*?```)", reply, flags=re.S)
    for i, piece in enumerate(pieces):
        if piece.startswith("```"):
            continue
        piece = _CITE_LINKED.sub(fix_linked, piece)
        piece = _CITE_BRACKETED.sub(fix_bracketed, piece)
        piece = _CITE_NUMERIC.sub(fix_numeric, piece)
        # Bare "Source 2" / "Sources 1 and 3", outside the links made above.
        parts = re.split(r"(\[Source \d+\]\(#source-\d+\))", piece)
        piece = "".join(p if p.startswith("[Source ") else _CITE_BARE.sub(fix_bare, p) for p in parts)
        pieces[i] = piece
    return "".join(pieces)


_EVIDENCE_STOP = {
    "the", "and", "for", "that", "this", "with", "from", "shall", "will", "which", "their", "there",
    "contract", "contracts", "agreement", "clause", "source", "sources", "borrower", "lender", "provided",
    "documents", "document", "state", "states", "stated", "according",
}


def _evidence_terms(text: str) -> set:
    text = (text or "").lower()
    numbers = set(re.findall(r"\d+(?:[.,]\d+)*%?", text))
    words = {w for w in re.findall(r"[a-z][a-z\-]{4,}", text) if w not in _EVIDENCE_STOP}
    return numbers | words


def likely_sources(reply: str, sources: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """For an answer that cites nothing: the sources that share the most
    figures and distinctive words with it, best first (numbers count
    double - a rate or amount in the answer points at its clause)."""
    answer = _evidence_terms(reply)
    if not answer:
        return sources[:limit]
    scored = []
    for position, src in enumerate(sources):
        shared = answer & _evidence_terms(src.get("text", ""))
        score = sum(2 if re.match(r"\d", t) else 1 for t in shared)
        if score:
            scored.append((-score, position, src))
    if not scored:
        return sources[: min(limit, 3)]
    scored.sort()
    return [src for _, _, src in scored[:limit]]


def _follow_up_search_text(query: str, history: List[Dict[str, str]]) -> str:
    """Without the router's rewrite, a short follow-up ("and for Peter?")
    is searched together with the previous question."""
    if len(query) >= 80:
        return query
    previous = next((t["content"] for t in reversed(history) if t.get("role") == "user"), "")
    return f"{previous} {query}".strip() if previous else query


@app.post("/chat")
def chat_endpoint(request: ChatRequest):
    """
    Answer a question about the stored contracts.

    1. Questions answerable from contract fields (highest/lowest amount,
       totals, counts, lookups, filters by lender/date/amount) are
       answered in code, exactly (see chat_router). Rankings and totals
       always cover all contracts; lookups cover the contracts the
       question names, else the open one.
    2. Everything else gets clause text and an LLM answer that must cite
       it: the whole contract(s) when the question names them or one is
       open; the best passage from every contract when the question is
       across contracts; otherwise the most relevant passages, with the
       model told how much of the portfolio they cover.
    """
    from .chat_router import (
        check_spec, execute_spec, follow_up_spec, heuristic_spec, is_aggregate, looks_across_contracts, resolve_named_contracts,
        route_question, sources_for_rows, structured_scope,
    )
    from .mcp.llm_agent import remove_reasoning_traces

    query = request.message.strip()
    if not query:
        raise HTTPException(status_code=400, detail="message is required")

    history = [
        {"role": t.role, "content": t.content}
        for t in (request.history or [])
        if t.content and t.content.strip()
    ][-8:]

    single = request.analysis_id if request.analysis_id not in (None, "", "all") else None
    all_analyses = store.list_analyses()
    selected = next((a for a in all_analyses if a.get("analysis_id") == single), None) if single else None
    if single and selected is None:
        raise HTTPException(
            status_code=404,
            detail="The selected contract no longer exists. Choose another contract or 'All contracts'.",
        )
    if not all_analyses:
        return {"reply": "No contracts have been uploaded yet.", "sources": [], "route": "none"}

    spec = route_question(llm, query, history)
    routed_by = "llm"
    router_model = getattr(llm._get_provider("quality"), "model", None)
    if spec is None:
        spec = heuristic_spec(query)
        routed_by = "heuristic" if spec is not None else "none"
    widened, already_shown = follow_up_spec(query, spec, request.previous_spec, request.previous_ids)
    if widened is not spec:
        spec, routed_by = widened, "follow-up"
    checked = check_spec(spec, query)
    if checked is not spec:
        print(f"[chat] structured spec can't answer this question; using clause text instead")
        spec = checked

    rewritten = spec.standalone_question.strip() if spec and spec.standalone_question else ""
    search_text = rewritten or (_follow_up_search_text(query, history) if history else query)
    # Names come from this question (and the router's rewrite of it), never
    # from the previous question merged in for search: "which has the
    # highest amount?" after asking about Julia is not about Julia.
    named, loose_only = resolve_named_contracts(f"{query} {rewritten}".strip(), spec, all_analyses)
    if loose_only and (
        (spec is not None and spec.kind == "structured" and is_aggregate(spec))
        or (spec is not None and spec.kind == "semantic" and spec.across_contracts)
        or looks_across_contracts(query)
    ):
        # A first name that happens to match a word ("Grace Period") must
        # not turn a question about all contracts into one about a single one.
        named = []

    # 1) Structured questions: exact answer from the directory.
    if spec is not None and spec.kind == "structured":
        scope, note = structured_scope(spec, all_analyses, named, selected)
        stored = len(scope)
        if already_shown:
            scope = [a for a in scope if a.get("analysis_id") not in already_shown]
            note = ((note + " ") if note else "") + (
                f"The other contracts: the {stored - len(scope)} already shown are left out."
            )
            if not scope:
                return {
                    "reply": f"There are no other contracts: all {stored} were in the previous answer.",
                    "sources": [], "route": "structured", "routed_by": routed_by,
                    "query_spec": spec.model_dump(), "model": None, "router_model": router_model,
                }
        run_spec = spec
        if named:
            # The named contracts are already the scope; a filename filter
            # holding a borrower's name would otherwise match nothing.
            run_spec = spec.model_copy(update={"filters": [f for f in spec.filters if f.field != "filename"]})
        result = execute_spec(run_spec, scope)
        answer = result["answer"]
        if note:
            answer = f"_{note}_\n\n{answer}"
        if stored > 1:
            # So a user checking the answer knows what it covered (e.g. a
            # folder upload still in progress).
            answer += f"\n\n_Based on the {stored} contracts currently stored._"
        return {
            "reply": answer,
            "sources": sources_for_rows(result["rows"]),
            "route": "structured",
            "routed_by": routed_by,
            "query_spec": spec.model_dump(),
            # Computed in code; the model only interpreted the question.
            "model": None,
            "router_model": router_model,
        }

    # 2) Semantic questions: clause text + LLM.
    def need_rag():
        if ensure_rag() is None:
            reason = _rag_init["error"] or "see the server log"
            raise HTTPException(
                status_code=503,
                detail=f"Contract search is not available right now ({reason[:200]}). "
                       f"It is retried automatically; try again in {_RAG_RETRY_SEC} seconds.",
            )
        return rag

    top_k = max(1, min(request.top_k, 10))
    passages: List[Dict[str, Any]] = []
    coverage = ""
    # "you're wrong about clauses 3 and 6": fetch those clauses directly -
    # the sentence itself says nothing about what they contain, so search
    # alone would miss them.
    asked_clauses = _clause_numbers(f"{query} {rewritten}")
    shorten_to_budget = False
    try:
        if named:
            targets = named[:_MAX_NAMED_CONTRACTS]
            per_contract = _SINGLE_CONTRACT_CHAR_BUDGET // len(targets)
            for record in targets:
                whole = _whole_contract_passages(record, per_contract)
                if whole is None:
                    # Too long to send whole: the best passages, within
                    # this contract's share of the budget.
                    found = need_rag().query(search_text, top_k=6, filter_by_analysis=record["analysis_id"])
                    share = max(400, per_contract // max(1, len(found)))
                    for p in found:
                        p["text"] = _focus_passage(p.get("text", ""), search_text, share)
                    whole = found
                passages.extend(whole)
            coverage = "The sources are from the contract(s) the question names: " + ", ".join(
                r.get("filename") or r["analysis_id"] for r in targets
            ) + "."
            if len(named) > len(targets):
                coverage += f" The question matches {len(named)} contracts; only the first {len(targets)} were read."
        elif selected is not None:
            whole = _whole_contract_passages(selected, _SINGLE_CONTRACT_CHAR_BUDGET)
            if whole is None:
                whole = need_rag().query(search_text, top_k=top_k, filter_by_analysis=single)
            passages = whole
        elif (spec is not None and spec.across_contracts) or looks_across_contracts(search_text) or asked_clauses:
            ids = [a["analysis_id"] for a in all_analyses]
            # Up to 3 passages per contract: an answer can span clauses
            # (regular interest in one, late interest in another).
            passages = need_rag().query_per_contract(search_text, ids, per_contract=3)
            shorten_to_budget = True  # after identical wording is merged
            covered = {p["analysis_id"] for p in passages}
            coverage = (
                f"The sources are the most relevant passages from each of {len(covered)} of the "
                f"{len(all_analyses)} contracts (long passages shortened with '…')."
            )
            missing = [a.get("filename") or a["analysis_id"] for a in all_analyses if a["analysis_id"] not in covered]
            if missing:
                coverage += " No relevant passage was found in: " + ", ".join(missing[:20]) + (" …" if len(missing) > 20 else "") + "."
        else:
            passages = need_rag().query(search_text, top_k=top_k)
            covered = {p["analysis_id"] for p in passages}
            coverage = (
                f"The sources are the {len(passages)} most relevant passages, from {len(covered)} of the "
                f"{len(all_analyses)} contracts. If the question needs every contract checked, say that "
                "this answer only covers the contracts in the sources."
            )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Contract search failed: {error}")

    if asked_clauses:
        # The clauses the question names, from every contract in scope,
        # ahead of the search results.
        if named:
            in_scope = named[:_MAX_NAMED_CONTRACTS]
        elif selected is not None:
            in_scope = [selected]
        else:
            in_scope = all_analyses
        pinned = []
        for record in in_scope:
            for n in asked_clauses:
                c = _clause_by_number(record, n)
                if c and str(c.get("text", "")).strip():
                    pinned.append({"analysis_id": record["analysis_id"], "clause_id": c.get("id"),
                                   "kind": "clause", "text": c["text"], "score": None})
        have = {(p.get("analysis_id"), str(p.get("clause_id"))) for p in pinned}
        passages = pinned + [p for p in passages if (p.get("analysis_id"), str(p.get("clause_id"))) not in have]
        coverage = (coverage + " " if coverage else "") + (
            "The question names clause(s) " + ", ".join(str(n) for n in asked_clauses)
            + "; those clauses are included first for every contract in scope."
        )

    names = {a.get("analysis_id"): (a.get("filename") or f"Contract {a.get('analysis_id')}") for a in all_analyses}
    context_parts, sources = [], []
    merged = _merge_identical(passages)
    if shorten_to_budget and merged:
        share = max(250, _ACROSS_CHAR_BUDGET // len(merged))
        for p in merged:
            p["text"] = _focus_passage(p["text"], search_text, share)
    for p in merged:
        text = p["text"]
        index = len(sources) + 1
        label = names.get(p.get("analysis_id"), f"Contract {p.get('analysis_id')}")
        where = "contract header (parties, amounts)" if p.get("kind") == "header" else f"clause {p.get('clause_id')}"
        others = [names.get(i, str(i)) for i in p["also_in"]]
        shared = ""
        if others:
            listed = ", ".join(others[:30]) + (f" and {len(others) - 30} more" if len(others) > 30 else "")
            shared = f" | identical wording also in: {listed}"
        context_parts.append(f"[Source {index} | {label} | {where}{shared}]\n{text}")
        sources.append({
            "source_number": index,
            "analysis_id": p.get("analysis_id"),
            "filename": label,
            "clause_id": p.get("clause_id"),
            "text": text,
            "score": p.get("score"),
            "kind": p.get("kind", "clause"),
            "also_in": [{"analysis_id": i, "filename": names.get(i, str(i))} for i in p["also_in"]],
        })

    # Directory rows only for the contracts being discussed; a short form
    # when there are many, so the prompt stays inside the context window.
    in_sources = {src["analysis_id"] for src in sources} | {
        o["analysis_id"] for src in sources for o in src.get("also_in", [])
    }
    discussed = [a for a in all_analyses if a.get("analysis_id") in in_sources or a is selected]
    if len(discussed) > 12:
        from .chat_router import format_money

        def short(a):
            cm = a.get("contract_metadata") or {}
            value = cm.get("contract_value")
            amount = format_money(float(value), cm.get("currency")) if isinstance(value, (int, float)) else "not found"
            return (f"- ID: {a.get('analysis_id')} | File: {a.get('filename')} | Borrower: "
                    f"{cm.get('customer_name') or 'not found'} | Lender: {cm.get('lender_name') or 'not found'} "
                    f"| Amount: {amount}")
        directory = "\n".join(short(a) for a in discussed)
    else:
        directory = "\n".join(_directory_line(a) for a in discussed)

    def build_prompt(turns: List[Dict[str, str]], parts: List[str]) -> str:
        return (
            _history_block(turns)
            + "Contracts directory (fields extracted from each document; 'not found' means the document doesn't state it):\n"
            + (directory or "(none)")
            + ("\n\nCoverage: " + coverage if coverage else "")
            + "\n\nSources:\n"
            + ("\n\n".join(parts) if parts else "(no passages matched this question)")
            + f"\n\nQuestion: {query}"
            + (f"\n(Meaning: {rewritten})" if rewritten and rewritten != query else "")
        )

    # Never send more than fits the model's context window: a cut-off
    # prompt fails, or worse, is answered without part of the sources.
    # Shed the older conversation first, then shorten the passages.
    prompt = build_prompt(history, context_parts)
    if len(prompt) > _MAX_PROMPT_CHARS:
        prompt = build_prompt(history[-2:], context_parts)
    if len(prompt) > _MAX_PROMPT_CHARS and context_parts:
        overflow = len(prompt) - _MAX_PROMPT_CHARS
        total = sum(len(c) for c in context_parts)
        ratio = max(0.1, 1 - overflow / max(1, total) - 0.02)
        trimmed = []
        for part, src in zip(context_parts, sources):
            head, _, body = part.partition("\n")
            body = _focus_passage(body, search_text, max(200, int(len(body) * ratio)))
            src["text"] = body
            trimmed.append(f"{head}\n{body}")
        context_parts = trimmed
        prompt = build_prompt(history[-2:], context_parts)
    if len(prompt) > _MAX_PROMPT_CHARS:
        # The sources matter more than the conversation.
        prompt = build_prompt([], context_parts)
    dropped = 0
    while len(prompt) > _MAX_PROMPT_CHARS and len(context_parts) > 1:
        # Last resort: drop the least relevant sources (they're ordered
        # best first within each contract), and say so.
        context_parts.pop()
        sources.pop()
        dropped += 1
        coverage = (coverage.split(" [")[0] + f" [{dropped} further passage(s) left out to fit; "
                    "the answer may not cover every contract.]")
        prompt = build_prompt([], context_parts)

    reply, answer_model, tried = _answer_with_fallback(prompt)
    if reply is None:
        raise HTTPException(
            status_code=503,
            detail="The AI server didn't produce an answer (" + "; ".join(tried)
            + "). Please try again in a minute.",
        )

    reply = link_citations(remove_reasoning_traces(str(reply)).strip(), len(sources))
    print(f"[chat] answered by {answer_model} (routing: {routed_by}, {len(sources)} sources)")
    # Show the sources the answer cites (numbers kept, so the inline links
    # still match). If it cites none, the passages it most likely drew on,
    # marked as such - an answer with no way to check it is worse.
    cited = set(_cited_source_numbers(reply))
    if cited:
        shown = [s for s in sources if s["source_number"] in cited]
        citations = "cited"
    else:
        shown = likely_sources(reply, sources)
        citations = "inferred" if shown else "none"

    return {
        "reply": reply,
        "sources": shown,
        "route": "semantic",
        "routed_by": routed_by,
        "citations": citations,
        "coverage": coverage,
        "model": answer_model,
        "router_model": router_model,
    }


term_labels = {
    "effective_date": "Effective Date",
    "contract_duration": "Contract Duration",
    "renewal_period": "Renewal Period",
    "payment_period": "Payment Period",
    "termination_notice": "Termination Notice",
    "liability_cap": "Liability Cap",
    "governing_law": "Governing Law",
    "jurisdiction": "Jurisdiction",
    "sla_uptime": "SLA Uptime",
    "breach_notification": (
        "Data Breach Notification"
    ),
}

term_patterns = {
    "effective_date": [
        (
            r"(?:effective\s+date|commences?\s+on|"
            r"effective\s+from)\s*(?:is|of|on|:)?\s*"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4}|"
            r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
            r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
        ),
    ],
    "contract_duration": [
        (
            r"(?:term|duration|period)\s*(?:of|is|:)?\s*"
            r"(\d+\s*\([^)]+\)\s*(?:year|month|day)s?|"
            r"\d+\s*(?:year|month|day)s?)"
        ),
        (
            r"(?:remain(?:s)?\s+in\s+force|continue)"
            r"\s+for\s+"
            r"(\d+\s*\([^)]+\)\s*(?:year|month|day)s?|"
            r"\d+\s*(?:year|month|day)s?)"
        ),
    ],
    "renewal_period": [
        (
            r"(?:renew(?:ed|al)?|automatic(?:ally)?\s+"
            r"renew(?:ed|al)?)"
            r".{0,80}?"
            r"(\d+\s*\([^)]+\)\s*(?:year|month|day)s?|"
            r"\d+\s*(?:year|month|day)s?)"
        ),
    ],
    "payment_period": [
        (
            r"(?:paid|payable|payment\s+shall\s+be\s+made)"
            r".{0,80}?"
            r"(?:within|net)\s+"
            r"(\d+\s*\([^)]+\)\s*(?:business\s+)?days?|"
            r"\d+\s*(?:business\s+)?days?)"
        ),
        (
            r"\bnet\s+(\d+)\b"
        ),
    ],
    "termination_notice": [
        (
            r"(?:terminate|termination)"
            r".{0,120}?"
            r"(?:notice\s+of|upon|with)\s+"
            r"(\d+\s*\([^)]+\)\s*(?:business\s+)?days?"
            r"(?:\s+written\s+notice)?|"
            r"\d+\s*(?:business\s+)?days?"
            r"(?:\s+written\s+notice)?)"
        ),
        (
            r"(\d+\s*(?:business\s+)?days?)"
            r"\s+(?:prior\s+)?written\s+notice"
        ),
    ],
    "liability_cap": [
        (
            r"(?:liability|aggregate\s+liability)"
            r".{0,120}?"
            r"(?:shall\s+not\s+exceed|limited\s+to|"
            r"capped\s+at|cap(?:ped)?\s+at)\s+"
            r"([^.;\n]+)"
        ),
        (
            r"(unlimited\s+liability)"
        ),
    ],
    "governing_law": [
        (
            r"(?:governed\s+by|governing\s+law)"
            r"(?:\s+the\s+laws?)?(?:\s+of)?\s*"
            r"([A-Za-z][A-Za-z\s,&-]{2,60})"
        ),
    ],
    "jurisdiction": [
        (
            r"(?:exclusive\s+jurisdiction|jurisdiction)"
            r"(?:\s+of|\s+in|\s+shall\s+be)?\s*"
            r"([A-Za-z][A-Za-z\s,&-]{2,60})"
        ),
    ],
    "sla_uptime": [
        (
            r"(\d{2,3}(?:\.\d+)?\s*%)"
            r".{0,40}?"
            r"(?:uptime|availability)"
        ),
        (
            r"(?:uptime|availability)"
            r".{0,40}?"
            r"(\d{2,3}(?:\.\d+)?\s*%)"
        ),
    ],
    "breach_notification": [
        (
            r"(?:security|data)\s+breach"
            r".{0,120}?"
            r"(?:within|no\s+later\s+than)\s+"
            r"(\d+\s*(?:hours?|days?))"
        ),
        (
            r"(?:notify|notification)"
            r".{0,80}?"
            r"(?:breach|security\s+incident)"
            r".{0,80}?"
            r"(\d+\s*(?:hours?|days?))"
        ),
    ],
}


def extract_structured_terms(
    analysis: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    results = analysis.get("results") or analysis.get("clauses") or []

    extracted: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for term_key, patterns in term_patterns.items():
        matches = []

        for clause in results:
            clause_text = str(
                clause.get("text", "")
            ).strip()

            if not clause_text:
                continue

            for pattern in patterns:
                match = re.search(
                    pattern,
                    clause_text,
                    flags=(
                        re.IGNORECASE
                        | re.DOTALL
                    ),
                )

                if not match:
                    continue

                value = re.sub(
                    r"\s+",
                    " ",
                    match.group(1).strip(),
                )

                existing_values = {
                    item["value"].lower()
                    for item in matches
                }

                if value.lower() in existing_values:
                    continue

                matches.append(
                    {
                        "value": value,
                        "clause_id": clause.get(
                            "id"
                        ),
                        "clause_text": (
                            clause_text
                        ),
                    }
                )

        if matches:
            extracted[term_key] = {
                "label": term_labels[
                    term_key
                ],
                "value": matches[0][
                    "value"
                ],
                "clause_id": matches[0][
                    "clause_id"
                ],
                "clause_text": matches[0][
                    "clause_text"
                ],
                "all_matches": matches,
                "has_conflict": (
                    len(
                        {
                            item[
                                "value"
                            ].lower()
                            for item in matches
                        }
                    )
                    > 1
                ),
            }

    return extracted


@app.post("/compare")
def compare_contracts(
    payload: Dict[str, Any] = Body(...),
):
    """Compare two previously analyzed contracts."""

    analysis_id_1 = payload.get("analysis_id_1")
    analysis_id_2 = payload.get("analysis_id_2")

    if not analysis_id_1 or not analysis_id_2:
        raise HTTPException(
            status_code=400,
            detail="Both analysis IDs are required",
        )

    if analysis_id_1 == analysis_id_2:
        raise HTTPException(
            status_code=400,
            detail="Select two different contracts to compare",
        )

    analysis_1 = store.get_analysis(analysis_id_1)
    analysis_2 = store.get_analysis(analysis_id_2)

    if not analysis_1 or not analysis_2:
        raise HTTPException(
            status_code=404,
            detail="One or both analyses were not found",
        )

    risk_weights = {
        "high": 5,
        "medium": 3,
        "low": 1,
    }
    


    def get_stats(
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        results = analysis.get("results") or analysis.get("clauses") or []

        high = 0
        medium = 0
        low = 0
        unclassified = 0

        domain_stats: Dict[
            str,
            Dict[str, Any],
        ] = {}

        for result in results:
            classification = (
                result.get("classification") or {}
            )

            risk_level = str(
                classification.get(
                    "risk_level",
                    "",
                )
            ).strip().lower()

            domain = str(
                classification.get(
                    "domain",
                    "Other",
                )
                or "Other"
            ).strip()

            if domain not in domain_stats:
                domain_stats[domain] = {
                    "total": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "unclassified": 0,
                }

            domain_stats[domain]["total"] += 1

            if risk_level == "high":
                high += 1
                domain_stats[domain]["high"] += 1

            elif risk_level == "medium":
                medium += 1
                domain_stats[domain]["medium"] += 1

            elif risk_level == "low":
                low += 1
                domain_stats[domain]["low"] += 1

            else:
                unclassified += 1
                domain_stats[domain]["unclassified"] += 1

        total_clauses = len(results)
        classified_clauses = high + medium + low

        weighted_points = (
            high * risk_weights["high"]
            + medium * risk_weights["medium"]
            + low * risk_weights["low"]
        )

        normalized_risk_score = (
            weighted_points / classified_clauses
            if classified_clauses > 0
            else 0
        )

        high_risk_percentage = (
            high / classified_clauses * 100
            if classified_clauses > 0
            else 0
        )

        medium_risk_percentage = (
            medium / classified_clauses * 100
            if classified_clauses > 0
            else 0
        )

        low_risk_percentage = (
            low / classified_clauses * 100
            if classified_clauses > 0
            else 0
        )

        for domain_data in domain_stats.values():
            domain_classified = (
                domain_data["high"]
                + domain_data["medium"]
                + domain_data["low"]
            )

            domain_weighted_points = (
                domain_data["high"]
                * risk_weights["high"]
                + domain_data["medium"]
                * risk_weights["medium"]
                + domain_data["low"]
                * risk_weights["low"]
            )

            domain_data["normalized_risk_score"] = round(
                (
                    domain_weighted_points
                    / domain_classified
                )
                if domain_classified > 0
                else 0,
                2,
            )

            domain_data["high_risk_percentage"] = round(
                (
                    domain_data["high"]
                    / domain_classified
                    * 100
                )
                if domain_classified > 0
                else 0,
                2,
            )

        return {
            "analysis_id": analysis.get("analysis_id"),
            "filename": analysis.get("filename"),
            "created_at": analysis.get("created_at"),
            "updated_at": analysis.get("updated_at"),
            "total_clauses": total_clauses,
            "classified_clauses": classified_clauses,
            "unclassified_clauses": unclassified,
            "high_risk": high,
            "medium_risk": medium,
            "low_risk": low,
            "high_risk_percentage": round(
                high_risk_percentage,
                2,
            ),
            "medium_risk_percentage": round(
                medium_risk_percentage,
                2,
            ),
            "low_risk_percentage": round(
                low_risk_percentage,
                2,
            ),
            "normalized_risk_score": round(
                normalized_risk_score,
                2,
            ),
            "weighted_risk_points": weighted_points,
            "domains": domain_stats,
        }

    contract_1 = get_stats(analysis_1)
    contract_2 = get_stats(analysis_2)
    
    terms_1 = extract_structured_terms(
    analysis_1
    )

    terms_2 = extract_structured_terms(
        analysis_2
    )

    contract_1["structured_terms"] = terms_1
    contract_2["structured_terms"] = terms_2

    score_1 = contract_1["normalized_risk_score"]
    score_2 = contract_2["normalized_risk_score"]

    high_rate_1 = contract_1[
        "high_risk_percentage"
    ]
    high_rate_2 = contract_2[
        "high_risk_percentage"
    ]

    safer_contract = None
    verdict = ""
    verdict_reasons: List[str] = []

    contract_1_name = (
        contract_1["filename"] or "Contract 1"
    )
    contract_2_name = (
        contract_2["filename"] or "Contract 2"
    )

    # A contract that hasn't been risk-analyzed has no risky clauses on
    # record - which is "unknown", not "safe".
    not_analyzed = [
        name for name, a in ((contract_1_name, analysis_1), (contract_2_name, analysis_2))
        if a.get("status") != "analyzed" or not a.get("results")
    ]
    if not_analyzed:
        verdict = (
            "Can't say which is safer: " + " and ".join(not_analyzed)
            + (" hasn't" if len(not_analyzed) == 1 else " haven't")
            + " been risk-analyzed yet. Run the analysis first."
        )
    elif score_1 < score_2:
        safer_contract = analysis_id_1
        verdict = (
            f"{contract_1_name} has the lower "
            "normalized risk score."
        )

    elif score_2 < score_1:
        safer_contract = analysis_id_2
        verdict = (
            f"{contract_2_name} has the lower "
            "normalized risk score."
        )

    elif high_rate_1 < high_rate_2:
        safer_contract = analysis_id_1
        verdict = (
            f"{contract_1_name} has the lower "
            "high-risk clause rate."
        )

    elif high_rate_2 < high_rate_1:
        safer_contract = analysis_id_2
        verdict = (
            f"{contract_2_name} has the lower "
            "high-risk clause rate."
        )

    else:
        verdict = (
            "The contracts have equal normalized "
            "risk scores and high-risk rates."
        )

    score_difference = round(
        score_1 - score_2,
        2,
    )

    high_risk_rate_difference = round(
        high_rate_1 - high_rate_2,
        2,
    )

    if score_1 != score_2:
        verdict_reasons.append(
            "Normalized risk scores are "
            f"{score_1} and {score_2}."
        )

    if high_rate_1 != high_rate_2:
        verdict_reasons.append(
            "High-risk clause rates are "
            f"{high_rate_1}% and {high_rate_2}%."
        )

    if (
        contract_1["unclassified_clauses"] > 0
        or contract_2["unclassified_clauses"] > 0
    ):
        verdict_reasons.append(
            "One or both contracts contain "
            "unclassified clauses."
        )

    if not verdict_reasons:
        verdict_reasons.append(
            "Both contracts have the same normalized "
            "risk score and high-risk clause rate."
        )

    all_domains = sorted(
        set(contract_1["domains"].keys())
        | set(contract_2["domains"].keys())
    )

    all_term_keys = list(term_labels.keys())

    term_comparison = []

    for term_key in all_term_keys:
        term_1 = terms_1.get(term_key)
        term_2 = terms_2.get(term_key)

        value_1 = (
            term_1.get("value")
            if term_1
            else None
        )

        value_2 = (
            term_2.get("value")
            if term_2
            else None
        )

        if value_1 and value_2:
            status = (
                "same"
                if value_1.strip().lower()
                == value_2.strip().lower()
                else "different"
            )

        elif value_1 and not value_2:
            status = "only_contract_1"

        elif value_2 and not value_1:
            status = "only_contract_2"

        else:
            status = "missing_both"

        term_comparison.append(
            {
                "key": term_key,
                "label": term_labels[
                    term_key
                ],
                "contract_1": term_1,
                "contract_2": term_2,
                "status": status,
            }
        )

    domain_comparison = []

    def empty_domain_stats() -> Dict[str, Any]:
        return {
            "total": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "unclassified": 0,
            "normalized_risk_score": 0,
            "high_risk_percentage": 0,
        }

    for domain in all_domains:
        domain_1 = contract_1["domains"].get(
            domain,
            empty_domain_stats(),
        )

        domain_2 = contract_2["domains"].get(
            domain,
            empty_domain_stats(),
        )

        domain_comparison.append(
            {
                "domain": domain,
                "contract_1": domain_1,
                "contract_2": domain_2,
                "score_difference": round(
                    domain_1[
                        "normalized_risk_score"
                    ]
                    - domain_2[
                        "normalized_risk_score"
                    ],
                    2,
                ),
            }
        )

    return {
        "contract_1": contract_1,
        "contract_2": contract_2,
        "comparison": {
            "clause_difference": (
                contract_1["total_clauses"]
                - contract_2["total_clauses"]
            ),
            "high_risk_difference": (
                contract_1["high_risk"]
                - contract_2["high_risk"]
            ),
            "normalized_score_difference": (
                score_difference
            ),
            "high_risk_rate_difference": (
                high_risk_rate_difference
            ),
            "safer_contract": safer_contract,
            "is_tie": safer_contract is None and not not_analyzed,
            "not_analyzed": not_analyzed,
            "verdict": verdict,
            "verdict_reasons": verdict_reasons,
            "domain_comparison": domain_comparison,
            "term_comparison": term_comparison,
        },
    }

# --- LLM Settings endpoints ---

@app.get("/settings")
def get_llm_settings():
    """Get current LLM settings and provider status."""
    return {
        "settings": get_settings(),
        "status": get_provider_status()
    }


@app.post("/settings")
def update_llm_settings(settings: Dict[str, Any] = Body(...)):
    """Update LLM settings (provider, model, url)."""
    filtered = {k: v for k, v in settings.items() if k in EDITABLE_SETTINGS}

    if "provider" in filtered and filtered["provider"] not in ["groq", "ollama"]:
        raise HTTPException(status_code=400, detail="Invalid provider. Must be 'groq' or 'ollama'")

    save_settings(filtered)
    load_settings()  # Reload to ensure consistency

    return {
        "message": "Settings updated",
        "settings": get_settings(),
        "status": get_provider_status()
    }


@app.get("/settings/test")
def test_llm_connection():
    """Test the current LLM provider connection."""
    from .llm_providers import get_llm_provider

    provider = get_llm_provider()
    provider_name = get_settings().get("provider", "groq")

    if not provider.is_available():
        return {
            "success": False,
            "provider": provider_name,
            "error": f"{provider_name.title()} is not available. Check configuration."
        }

    try:
        response = provider.invoke("Say 'OK' if you can read this.", temperature=0)
        return {
            "success": True,
            "provider": provider_name,
            "response": response[:100]  # Truncate for safety
        }
    except Exception as e:
        return {
            "success": False,
            "provider": provider_name,
            "error": str(e)
        }
