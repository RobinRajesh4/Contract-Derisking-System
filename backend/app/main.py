from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from typing import List as TypingList
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import orjson
from dotenv import load_dotenv

# Load env from .env (GROQ_API_KEY, QDRANT_URL, etc.)
load_dotenv()

from .parser import extract_text_from_file, split_into_clauses, extract_metadata
from .store import Store
from .mcp.llm_agent import LLMClient
from .policy import save_policy, get_policy, list_policies, apply_policy
from .llm_providers import get_settings, save_settings, get_provider_status, load_settings
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



@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    try:
        content = await file.read()
        text, ocr_info = extract_text_from_file(file.filename, content)
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="No text could be extracted from the file")
        clauses = split_into_clauses(text)
        items = []
        for idx, clause_text in enumerate(clauses, start=1):
            meta = extract_metadata(clause_text)
            items.append({
                "id": idx,
                "text": clause_text,
                "metadata": meta,
            })
        analysis_id = store.save_analysis({
            "filename": file.filename,
            "clauses": items,
            "status": "uploaded",
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "file_size": len(content),
            "ocr_info": ocr_info,
        })
        # Upsert clauses into Qdrant for later retrieval (best-effort)
        if rag is not None:
            try:
                rag.upsert_clauses(
                    analysis_id,
                    items,
                )

                print(
                    f"Indexed {len(items)} clauses "
                    f"for analysis {analysis_id}"
                )

            except Exception as error:
                print(
                    f"RAG indexing failed for "
                    f"{analysis_id}: {error}"
                )
        return {
            "analysis_id": analysis_id, 
            "total_clauses": len(items),
            "ocr_info": ocr_info
        }
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
            text, ocr_info = extract_text_from_file(file.filename, content)
            if not text or not text.strip():
                errors.append({"filename": file.filename, "error": "No text could be extracted"})
                continue
                
            clauses = split_into_clauses(text)
            items = []
            for idx, clause_text in enumerate(clauses, start=1):
                meta = extract_metadata(clause_text)
                items.append({
                    "id": idx,
                    "text": clause_text,
                    "metadata": meta,
                })
            
            analysis_id = store.save_analysis({
                "filename": file.filename,
                "clauses": items,
                "status": "uploaded",
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "file_size": len(content),
                "ocr_info": ocr_info,
            })
            
            if rag is not None:
                try:
                    rag.upsert_clauses(
                        analysis_id,
                        items,
                    )

                    print(
                        f"Indexed {len(items)} clauses "
                        f"for analysis {analysis_id}"
                    )

                except Exception as error:
                    print(
                        f"RAG indexing failed for "
                        f"{analysis_id}: {error}"
                    )
            
            results.append({
                "filename": file.filename,
                "analysis_id": analysis_id,
                "total_clauses": len(items),
                "ocr_info": ocr_info
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
async def analyze(payload: AnalyzeRequest):
    # determine source text
    if payload.analysis_id:
        record = store.get_analysis(payload.analysis_id)
        if not record:
            raise HTTPException(status_code=404, detail="analysis_id not found")
        clauses = record.get("clauses", [])
    elif payload.text:
        clauses_text = split_into_clauses(payload.text)
        clauses = [{"id": i+1, "text": t, "metadata": extract_metadata(t)} for i, t in enumerate(clauses_text)]
        # persist a transient analysis
        analysis_id = store.save_analysis({
            "filename": None,
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
    for c in clauses:
        ctx = None
        if rag is not None:
            try:
                # Retrieve similar clauses (cross-analysis). Tune top_k via env if needed.
                ctx = rag.query(c.get("text", ""), top_k=5)
            except Exception:
                ctx = None
        classification = llm.classify_clause(c["text"], c.get("metadata", {}), context=ctx)
        # merge
        result = {
            **c,
            "classification": classification,
            "title": _make_title(c.get("text", ""), classification or {}),
        }
        results.append(result)

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
        enriched, summary = apply_policy(results, policy_obj)
        results = enriched
        policy_summary = summary

    # update store
    update_payload: Dict[str, Any] = {
        "status": "analyzed",
        "results": results,
    }
    if policy_summary:
        update_payload["policy_summary"] = policy_summary
    store.update_analysis(payload.analysis_id, update_payload)

    return AnalyzeResponse(
        analysis_id=payload.analysis_id,
        total_clauses=len(results),
        results=results,
        policy_summary=policy_summary,
    )


@app.get("/rag/status")
async def rag_status():
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
async def list_analyses():
    return store.list_analyses()


@app.get("/clauses/{analysis_id}")
async def get_analysis(analysis_id: str):
    data = store.get_analysis(analysis_id)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return data


@app.get("/")
async def root():
    return {"status": "ok"}


# --- Policy management endpoints ---

@app.post("/policy")
async def upsert_policy(policy: Dict[str, Any] = Body(...)):
    try:
        pid = save_policy(policy)
        return {"policy_id": pid, "status": "saved"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@app.get("/policy/{policy_id}")
async def get_policy_endpoint(policy_id: str):
    p = get_policy(policy_id)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p


@app.get("/policies")
async def list_policies_endpoint():
    return list_policies()


@app.post("/recommend")
async def generate_recommendation(payload: Dict[str, Any] = Body(...)):
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
async def generate_summary(analysis_id: str):
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


class ChatRequest(BaseModel):
    message: str
    analysis_id: Optional[str] = None
    top_k: int = 5


class ChatRequest(BaseModel):
    message: str
    analysis_id: Optional[str] = None
    top_k: int = 5


@app.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
):
    """
    Chat with indexed contracts using local Qdrant retrieval.

    If analysis_id is provided, retrieval is restricted to
    that particular contract. Otherwise, all indexed
    contracts are searched.
    """

    if rag is None:
        raise HTTPException(
            status_code=503,
            detail="RAG system is not initialized",
        )

    query = request.message.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="message is required",
        )

    top_k = max(
        1,
        min(request.top_k, 10),
    )

    try:
        results = rag.query(
            query,
            top_k=top_k,
            filter_by_analysis=request.analysis_id,
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Contract retrieval failed: "
                f"{error}"
            ),
        )

    if not results:
        return {
            "reply": (
                "I could not find any relevant contract "
                "clauses to answer that question."
            ),
            "sources": [],
        }

    context_parts = []
    sources = []

    for index, result in enumerate(
        results,
        start=1,
    ):
        clause_text = str(
            result.get("text", "")
        ).strip()

        if not clause_text:
            continue

        context_parts.append(
            f"[Source {index}]\n{clause_text}"
        )

        sources.append(
            {
                "source_number": index,
                "analysis_id": result.get(
                    "analysis_id"
                ),
                "clause_id": result.get(
                    "clause_id"
                ),
                "text": clause_text,
                "score": result.get("score"),
            }
        )

    if not context_parts:
        return {
            "reply": (
                "Relevant records were found, but no "
                "readable clause text was available."
            ),
            "sources": [],
        }

    context = "\n\n".join(
        context_parts
    )

    prompt = f"""
Use only the contract excerpts below to answer the question.

If the answer is not supported by the excerpts, say:
"I do not know based on the provided contract documents."

Do not invent contract terms.
Refer to source numbers when appropriate.
Keep the answer concise and clear.

Contract excerpts:

{context}

Question:

{query}
""".strip()

    system_prompt = """
You are a contract question-answering assistant.

Answer only using the supplied contract excerpts.
Do not invent information.
Do not provide unsupported conclusions.
Explain that the response is not legal advice when appropriate.
""".strip()

    provider = llm._get_provider()

    if not provider.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "The configured AI provider is unavailable. "
                "Check the Ollama or Groq settings."
            ),
        )

    try:
        reply = provider.invoke(
            prompt,
            system=system_prompt,
            temperature=0,
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "AI response generation failed: "
                f"{error}"
            ),
        )

    return {
        "reply": str(reply).strip(),
        "sources": sources,
    }

@app.post("/compare")
async def compare_contracts(payload: Dict[str, Any] = Body(...)):
    """Compare two contract analyses side by side."""
    analysis_id_1 = payload.get("analysis_id_1")
    analysis_id_2 = payload.get("analysis_id_2")
    
    if not analysis_id_1 or not analysis_id_2:
        raise HTTPException(status_code=400, detail="Both analysis IDs required")
    
    analysis1 = store.get_analysis(analysis_id_1)
    analysis2 = store.get_analysis(analysis_id_2)
    
    if not analysis1 or not analysis2:
        raise HTTPException(status_code=404, detail="One or both analyses not found")
    
    def get_stats(analysis):
        results = analysis.get("results", analysis.get("clauses", []))
        high = sum(1 for r in results if (r.get('classification', {}).get('risk_level', '')).lower() == 'high')
        medium = sum(1 for r in results if (r.get('classification', {}).get('risk_level', '')).lower() == 'medium')
        low = sum(1 for r in results if (r.get('classification', {}).get('risk_level', '')).lower() == 'low')
        return {
            "total_clauses": len(results),
            "high_risk": high,
            "medium_risk": medium,
            "low_risk": low,
            "filename": analysis.get("filename"),
            "created_at": analysis.get("created_at")
        }
    
    return {
        "contract_1": get_stats(analysis1),
        "contract_2": get_stats(analysis2),
        "comparison": {
            "clause_difference": get_stats(analysis1)["total_clauses"] - get_stats(analysis2)["total_clauses"],
            "risk_difference": get_stats(analysis1)["high_risk"] - get_stats(analysis2)["high_risk"],
            "safer_contract": analysis_id_1 if get_stats(analysis1)["high_risk"] < get_stats(analysis2)["high_risk"] else analysis_id_2
        }
    }


# --- LLM Settings endpoints ---

@app.get("/settings")
async def get_llm_settings():
    """Get current LLM settings and provider status."""
    return {
        "settings": get_settings(),
        "status": get_provider_status()
    }


@app.post("/settings")
async def update_llm_settings(settings: Dict[str, Any] = Body(...)):
    """Update LLM settings (provider, model, url)."""
    allowed_keys = ["provider", "ollama_url", "ollama_model", "groq_model"]
    filtered = {k: v for k, v in settings.items() if k in allowed_keys}

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
async def test_llm_connection():
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
