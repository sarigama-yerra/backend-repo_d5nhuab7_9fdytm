import os
from datetime import datetime, timedelta
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import bcrypt
import jwt
import requests
from dotenv import load_dotenv

from database import db, create_document, get_documents, get_document_by_id, update_document_by_id, increment_field_by_id
from schemas import (
    AdminCreate,
    AdminDB,
    ClientCreate,
    ClientUpdate,
    ClientDB,
    TransactionLog,
    WithdrawRequest,
    TransferRequest,
    AdminLoginRequest,
    AdminLoginResponse,
)

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "devsecret")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "120"))

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "secret")

app = FastAPI(title="Zenith Broking API")

origins = [
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    message: str


def create_jwt(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_jwt(token: str) -> Dict[str, Any]:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


async def auth_dependency(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header missing")
    token = authorization.split(" ", 1)[1]
    return verify_jwt(token)


@app.get("/", response_model=Message)
async def root():
    return Message(message="Zenith Broking API is running")


@app.post("/api/admin/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest):
    admin = db["admin"].find_one({"email": payload.email})
    if not admin:
        # bootstrap: create admin if none
        password_hash = bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode()
        admin_id = create_document("admin", {"email": payload.email, "password_hash": password_hash})
        token = create_jwt({
            "sub": str(admin_id),
            "email": payload.email,
            "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRES_MINUTES),
        })
        return AdminLoginResponse(token=token, email=payload.email)

    if not bcrypt.checkpw(payload.password.encode(), admin["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt({
        "sub": str(admin.get("_id")),
        "email": payload.email,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRES_MINUTES),
    })
    return AdminLoginResponse(token=token, email=payload.email)


@app.get("/api/clients")
async def list_clients(user=Depends(auth_dependency)):
    clients = get_documents("client")
    return {"clients": clients}


@app.post("/api/clients")
async def add_client(payload: ClientCreate, user=Depends(auth_dependency)):
    client_id = create_document("client", payload.model_dump())
    return {"id": client_id}


@app.patch("/api/clients/{client_id}")
async def update_client(client_id: str, payload: ClientUpdate, user=Depends(auth_dependency)):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = update_document_by_id("client", client_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"status": "updated"}


@app.post("/api/withdraw")
async def withdraw(payload: WithdrawRequest, user=Depends(auth_dependency)):
    client = get_document_by_id("client", payload.client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.get("capital", 0) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # Razorpay Payouts API (mock call; replace fund_account_id/contacts etc. per your setup)
    try:
        response = requests.post(
            "https://api.razorpay.com/v1/payouts",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={
                "account_number": os.getenv("RAZORPAY_SOURCE_ACCOUNT", "000000000000"),
                "fund_account_id": os.getenv("RAZORPAY_FUND_ACCOUNT_ID", "fa_XXXX"),
                "amount": int(payload.amount * 100),
                "currency": "INR",
                "mode": "IMPS",
                "purpose": "payout",
                "queue_if_low_balance": True,
                "reference_id": f"wd_{payload.client_id}_{int(datetime.utcnow().timestamp())}",
                "narration": payload.note or "Withdrawal",
            },
            timeout=10,
        )
        rp_status = response.status_code
        rp_body = response.json() if response.content else {}
    except Exception as e:
        rp_status = 500
        rp_body = {"error": str(e)}

    # Deduct balance and log regardless of external success - adjust to your policy
    increment_field_by_id("client", payload.client_id, {"capital": -payload.amount})
    log_id = create_document("transactionlog", {
        "client_id": payload.client_id,
        "amount": payload.amount,
        "action": "withdraw",
        "timestamp": datetime.utcnow().isoformat(),
        "note": payload.note,
        "external": {"status": rp_status, "body": rp_body},
    })

    return {"status": "processed", "log_id": log_id, "razorpay": {"status": rp_status, "body": rp_body}}


@app.post("/api/transfer")
async def transfer(payload: TransferRequest, user=Depends(auth_dependency)):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    from_client = get_document_by_id("client", payload.from_client_id)
    to_client = get_document_by_id("client", payload.to_client_id)
    if not from_client or not to_client:
        raise HTTPException(status_code=404, detail="Client not found")
    if from_client.get("capital", 0) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # decrement from, increment to
    increment_field_by_id("client", payload.from_client_id, {"capital": -payload.amount})
    increment_field_by_id("client", payload.to_client_id, {"capital": payload.amount})

    # Optional external payout to to_client using Razorpay
    try:
        response = requests.post(
            "https://api.razorpay.com/v1/payouts",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={
                "account_number": os.getenv("RAZORPAY_SOURCE_ACCOUNT", "000000000000"),
                "fund_account_id": os.getenv("RAZORPAY_FUND_ACCOUNT_ID", "fa_XXXX"),
                "amount": int(payload.amount * 100),
                "currency": "INR",
                "mode": "IMPS",
                "purpose": "payout",
                "queue_if_low_balance": True,
                "reference_id": f"tf_{payload.from_client_id}_{payload.to_client_id}_{int(datetime.utcnow().timestamp())}",
                "narration": payload.note or "Transfer",
            },
            timeout=10,
        )
        rp_status = response.status_code
        rp_body = response.json() if response.content else {}
    except Exception as e:
        rp_status = 500
        rp_body = {"error": str(e)}

    log_id = create_document("transactionlog", {
        "client_id": payload.to_client_id,
        "amount": payload.amount,
        "action": "transfer",
        "timestamp": datetime.utcnow().isoformat(),
        "note": payload.note,
        "external": {"status": rp_status, "body": rp_body},
    })

    return {"status": "processed", "log_id": log_id, "razorpay": {"status": rp_status, "body": rp_body}}


# Twelve Data proxy (optional) to hide API key on client; set TWELVE_DATA_KEY
@app.get("/api/market/quote")
async def market_quote(symbol: str):
    key = os.getenv("TWELVE_DATA_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="Twelve Data API key not configured")
    r = requests.get("https://api.twelvedata.com/quote", params={"symbol": symbol, "apikey": key}, timeout=10)
    return r.json()


# Deployment notes:
# - Put secrets in .env: DATABASE_URL, DATABASE_NAME, JWT_SECRET, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_SOURCE_ACCOUNT, RAZORPAY_FUND_ACCOUNT_ID, TWELVE_DATA_KEY, FRONTEND_URL
# - Deploy backend on Render or Railway. Set environment variables there. Use a MongoDB Atlas connection string for DATABASE_URL.
# - CORS allowed for your frontend domain.
