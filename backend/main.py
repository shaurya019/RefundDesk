"""FastAPI app: the guarded RefundDesk API.

Identity is demo-grade: the UI's pickers send X-Patient-Id / X-Staff-Id headers. In a real app
these come from authentication. What matters here is WHERE they're used: the patient id
decides which invoices the validators accept; only staff ids can approve.

  GET  /api/health                     mode, model, limits
  GET  /api/people                     patients and staff for the pickers
  GET  /api/invoices                   the patient's invoices (X-Patient-Id)
  POST /api/requests                   submit a billing request -> full RequestResult with guard ledger
  GET  /api/requests, /api/requests/{id}
  GET  /api/approvals?status=pending
  POST /api/approvals/{id}/approve     (X-Staff-Id) re-validates with the action guard, then refunds
  POST /api/approvals/{id}/reject
  GET  /api/validators, /api/samples, /api/stats
  POST /api/demo/reset                 reseed demo data (scripted mode only)

Endpoints are plain `def`: Guardrails' guard calls are synchronous, so FastAPI runs them in its
thread pool and the event loop stays free.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import guards
from .agent import RefundAgent
from .db import PATIENTS, STAFF, Store
from .llm import LLM, OpenAILLM, ScriptedLLM
from .samples import SAMPLES
from .schemas import Approval, DecisionIn, Invoice, Person, RequestIn, RequestResult, Sample
from .settings import Settings

PATIENT_IDS = {p.id for p in PATIENTS}
STAFF_IDS = {s.id for s in STAFF}


def build_llm(settings: Settings) -> LLM:
    if settings.llm_mode == "scripted":
        return ScriptedLLM()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env, or set LLM_MODE=scripted to try the app offline.")
    return OpenAILLM(settings.openai_api_key, settings.openai_model, settings.reasoning_effort)


def create_app(settings: Settings | None = None, store: Store | None = None,
               llm_factory: Callable[[Settings], LLM] | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st = store or Store.connect(settings.mongo_uri, settings.mongo_db)
        st.seed()
        app.state.store = st
        app.state.agent = RefundAgent(st, (llm_factory or build_llm)(settings), settings)
        yield

    app = FastAPI(title="RefundDesk (Guardrails AI)", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Patient-Id", "X-Staff-Id"])

    def patient(x_patient_id: str | None) -> str:
        if x_patient_id not in PATIENT_IDS:
            raise HTTPException(status_code=401, detail="Pick a patient first.")
        return x_patient_id

    def staff(x_staff_id: str | None) -> str:
        if x_staff_id not in STAFF_IDS:
            raise HTTPException(status_code=403, detail="Only billing staff can decide approvals.")
        return x_staff_id

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "llm_mode": settings.llm_mode,
                "model": settings.openai_model if settings.llm_mode == "openai" else "scripted (offline demo)",
                "auto_approve_limit": settings.auto_approve_limit, "num_reasks": settings.num_reasks}

    @app.get("/api/people")
    def people() -> dict[str, list[Person]]:
        return {"patients": PATIENTS, "staff": STAFF}

    @app.get("/api/invoices", response_model=list[Invoice])
    def invoices(x_patient_id: str | None = Header(default=None)) -> list[Invoice]:
        return app.state.store.invoices_for(patient(x_patient_id))

    @app.post("/api/requests", response_model=RequestResult)
    def submit(req: RequestIn, x_patient_id: str | None = Header(default=None)) -> RequestResult:
        pid = patient(x_patient_id)
        try:
            return app.state.agent.handle(pid, req.message)
        except Exception as exc:     # never leak a stack trace to the client
            raise HTTPException(status_code=502, detail=f"Processing failed: {type(exc).__name__}") from exc

    @app.get("/api/requests", response_model=list[RequestResult])
    def requests(limit: int = Query(default=30, ge=1, le=100)) -> list[RequestResult]:
        return app.state.store.recent_requests(limit)

    @app.get("/api/requests/{request_id}", response_model=RequestResult)
    def request_detail(request_id: str) -> RequestResult:
        r = app.state.store.get_request(request_id)
        if r is None:
            raise HTTPException(status_code=404, detail="No such request.")
        return r

    @app.get("/api/approvals", response_model=list[Approval])
    def approvals(status: str | None = Query(default=None, pattern="^(pending|approved|rejected|failed)$")) -> list[Approval]:
        return app.state.store.list_approvals(status)

    def decide(approval_id: str, staff_id: str, approve: bool, note: str) -> Approval:
        st: Store = app.state.store
        doc = st.claim_approval(approval_id, staff_id, approve, note)
        if doc is None:
            raise HTTPException(status_code=409, detail="This approval is not pending anymore.")
        if not approve:
            return st.finish_approval(approval_id, "rejected", "Rejected by staff. No refund issued.")
        ok, detail, _run = app.state.agent.execute_refund(
            doc["patient_id"], {"invoice_id": doc["invoice_id"], "amount": doc["amount"]}, doc["request_id"], by=staff_id)
        return st.finish_approval(approval_id, "approved" if ok else "failed", detail)

    @app.post("/api/approvals/{approval_id}/approve", response_model=Approval)
    def approve(approval_id: str, body: DecisionIn, x_staff_id: str | None = Header(default=None)) -> Approval:
        return decide(approval_id, staff(x_staff_id), True, body.note)

    @app.post("/api/approvals/{approval_id}/reject", response_model=Approval)
    def reject(approval_id: str, body: DecisionIn, x_staff_id: str | None = Header(default=None)) -> Approval:
        return decide(approval_id, staff(x_staff_id), False, body.note)

    @app.get("/api/validators")
    def validators() -> list[dict]:
        return guards.validators_catalog()

    @app.get("/api/samples", response_model=list[Sample])
    def samples() -> list[Sample]:
        return SAMPLES

    @app.get("/api/stats")
    def stats() -> dict:
        return app.state.store.stats()

    @app.post("/api/demo/reset")
    def reset() -> dict:
        if settings.llm_mode != "scripted":
            raise HTTPException(status_code=403, detail="Reset is only available in scripted demo mode.")
        app.state.store.seed(reset=True)
        return {"status": "reset"}

    return app


app = create_app()
