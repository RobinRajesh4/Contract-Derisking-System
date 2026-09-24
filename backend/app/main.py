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
        uploads_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "uploaded_files"
        )
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
llm = LLMClient()
rag = None

if RAGStore is not None:
    try:
        rag = RAGStore()
        print("RAG system enabled")

    except Exception as error:
        print(
            "RAG system failed to initialize: "
            f"{error}"
        )
        rag = None

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

    with _ingest_lock:
        existing = store.get_analysis(analysis_id) if analysis_id else None
        if existing is None:
            existing = store.find_by_content_hash(content_hash)
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
                })
            store.update_analysis(analysis_id, fields)
        else:
            analysis_id = store.save_analysis({
                **fields,
                "status": "uploaded",
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            })

    _persist_original_file(analysis_id, filename, content, content_type)

    indexed = 0
    if rag is not None:
        try:
            indexed = rag.index_analysis(analysis_id, doc["clauses"], doc["header"])
            print(f"Indexed {indexed} passages for analysis {analysis_id}")
        except Exception as error:
            print(f"RAG indexing failed for {analysis_id}: {error}")

    return {
        "analysis_id": analysis_id,
        "total_clauses": len(doc["clauses"]),
        "ocr_info": ocr_info,
        "reprocessed": reprocessed,
        "clauses_changed": clauses_changed,
        "parse_quality": doc["parse_quality"],
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

    if policy_obj:
        enriched, summary = apply_policy(results, policy_obj, llm=llm)
        results = enriched
        policy_summary = summary

    # update store
    update_payload: Dict[str, Any] = {
        "status": "analyzed",
        "results": results,
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

    if executive_summary:
        update_payload["summary"] = executive_summary

    store.update_analysis(payload.analysis_id, update_payload)

    return AnalyzeResponse(
        analysis_id=payload.analysis_id,
        total_clauses=len(results),
        results=results,
        policy_summary=policy_summary,
    )


@app.get("/rag/status")
def rag_status():
    if rag is None:
        return {"enabled": False}
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
    
    clauses = analysis.get("results", analysis.get("clauses", []))
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
   sources or the directory. Cite the source it came from as [Source N](#source-N).
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
   [View](#contract-<ID>) using the directory ID.
6. When drafting clause wording, put the draft in a blockquote, separate from
   your explanation.
7. Be concise. Don't repeat caveats.
""".strip()


def _history_block(history: List[Dict[str, str]]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-6:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {str(turn.get('content', ''))[:1500]}")
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


@app.post("/chat")
def chat_endpoint(request: ChatRequest):
    """
    Answer a question about the stored contracts.

    1. Questions answerable from contract fields (highest/lowest amount,
       totals, counts, lookups, filters by lender/date/amount) are
       answered in code, exactly, with each contract's header as the
       reference (see chat_router).
    2. Everything else gets the relevant passages (or the whole contract,
       when one contract is selected) and an LLM answer that must cite them.
    """
    from .chat_router import execute_spec, route_question, sources_for_rows
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
    scope = [a for a in all_analyses if a.get("analysis_id") == single] if single else all_analyses
    if single and not scope:
        raise HTTPException(status_code=404, detail="analysis_id not found")

    # 1) Structured questions: exact answer from the directory.
    spec = route_question(llm, query, history)
    if spec is not None and spec.kind == "structured":
        result = execute_spec(spec, scope)
        return {
            "reply": result["answer"],
            "sources": sources_for_rows(result["rows"]),
            "route": "structured",
            "query_spec": spec.model_dump(),
        }

    # 2) Semantic questions: passages + LLM.
    passages: List[Dict[str, Any]] = []
    if single:
        record = scope[0]
        header = record.get("header")
        clauses = record.get("clauses") or []
        total_chars = len((header or {}).get("text", "")) + sum(len(c.get("text", "")) for c in clauses)
        if total_chars <= _SINGLE_CONTRACT_CHAR_BUDGET:
            if header and header.get("text"):
                passages.append({"analysis_id": single, "clause_id": "header", "kind": "header", "text": header["text"], "score": None})
            passages.extend(
                {"analysis_id": single, "clause_id": c.get("id"), "kind": "clause", "text": c.get("text", ""), "score": None}
                for c in clauses
            )

    if not passages:
        if rag is None:
            raise HTTPException(status_code=503, detail="Contract search is not available (RAG failed to start; see the server log).")
        top_k = max(1, min(request.top_k, 10))
        try:
            passages = rag.query(query, top_k=top_k, filter_by_analysis=single)
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"Contract search failed: {error}")

    names = {a.get("analysis_id"): (a.get("filename") or f"Contract {a.get('analysis_id')}") for a in all_analyses}
    context_parts, sources = [], []
    for index, p in enumerate(passages, start=1):
        text = str(p.get("text", "")).strip()
        if not text:
            continue
        label = names.get(p.get("analysis_id"), f"Contract {p.get('analysis_id')}")
        where = "contract header (parties, amounts)" if p.get("kind") == "header" else f"clause {p.get('clause_id')}"
        context_parts.append(f"[Source {index} | {label} | {where}]\n{text}")
        sources.append({
            "source_number": index,
            "analysis_id": p.get("analysis_id"),
            "filename": label,
            "clause_id": p.get("clause_id"),
            "text": text,
            "score": p.get("score"),
            "kind": p.get("kind", "clause"),
        })

    # Directory rows only for the contracts being discussed, so the
    # prompt doesn't grow with every contract ever uploaded.
    cited = {src["analysis_id"] for src in sources}
    directory = "\n".join(
        _directory_line(a) for a in scope if single or a.get("analysis_id") in cited
    )
    prompt = (
        _history_block(history)
        + "Contracts directory (fields extracted from each document; 'not found' means the document doesn't state it):\n"
        + (directory or "(none)")
        + "\n\nSources:\n"
        + ("\n\n".join(context_parts) if context_parts else "(no passages matched this question)")
        + f"\n\nQuestion: {query}"
    )

    provider = llm._get_provider("quality")
    if not provider.is_available():
        raise HTTPException(status_code=503, detail="The configured AI provider is unavailable. Check the Ollama or Groq settings.")
    try:
        reply = provider.invoke(prompt, system=CHAT_SYSTEM_PROMPT, temperature=0)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"AI response generation failed: {error}")

    return {
        "reply": remove_reasoning_traces(str(reply)).strip(),
        "sources": sources,
        "route": "semantic",
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
    results = analysis.get(
        "results",
        analysis.get("clauses", []),
    )

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
        results = analysis.get(
            "results",
            analysis.get("clauses", []),
        )

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

    if score_1 < score_2:
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
            "is_tie": safer_contract is None,
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
