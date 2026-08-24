from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
from sqlalchemy import create_engine, text, MetaData, Table, Column, String, JSON, Boolean
from psycopg2.extras import Json
from pwdlib import PasswordHash
import jwt
import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
password_hash = PasswordHash.recommended()

metadata = MetaData()

client_sessions = Table(
    "client_sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("tool_name", String, nullable=False),
    Column("advisor_id", String, nullable=False),
    Column("company_id", String, nullable=False),
    Column("client_id", String, nullable=True),
    Column("response_payload", JSON, nullable=False),
    Column("score_payload", JSON, nullable=True),
    Column("summary_payload", JSON, nullable=True),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
)

clients = Table(
    "clients",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("advisor_id", String, nullable=False),
    Column("first_name", String, nullable=False),
    Column("last_name", String, nullable=False),
    Column("email", String, nullable=False),
    Column("created_at", String, nullable=False),
)


advisors = Table(
    "advisors",
    metadata,
    Column("id", String, primary_key=True),
    Column("company_id", String, nullable=False),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("created_at", String, nullable=False),
)

metadata.create_all(engine, tables=[advisors])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60
security = HTTPBearer()

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required")


class ClientSessionCreate(BaseModel):
    tool_name: str
    advisor_id: str
    company_id: str
    client_id: str | None = None
    response_payload: dict
    score_payload: dict | None = None
    summary_payload: dict | None = None


class ClientCreate(BaseModel):
    invite_token: str
    first_name: str
    last_name: str
    email: str

class AdvisorLogin(BaseModel):
    email: str
    password: str


def get_current_advisor(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return {
        "advisor_id": payload["sub"],
        "company_id": payload["company_id"],
        "role": payload["role"]
    }

def create_client_invite_token(advisor_id: str, company_id: str):
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    return jwt.encode(
        {
            "advisor_id": advisor_id,
            "company_id": company_id,
            "type": "client_invite",
            "exp": expires_at
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )


# --- ROUTES ---
@app.post("/client-invite")
def create_client_invite(
    current_advisor: dict = Depends(get_current_advisor)
):
    token = create_client_invite_token(
        current_advisor["advisor_id"],
        current_advisor["company_id"]
    )

    return {
        "ok": True,
        "invite_token": token
    }

def verify_client_invite_token(token: str):
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Client invite expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid client invite")

    if payload.get("type") != "client_invite":
        raise HTTPException(status_code=401, detail="Invalid client invite")

    return {
        "advisor_id": payload["advisor_id"],
        "company_id": payload["company_id"]
    }



@app.get("/")
def root():
    return {"message": "advisor backend is running"}

@app.post("/client-sessions")
def create_client_session(payload: ClientSessionCreate):
    session_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO client_sessions (
                id, tool_name, advisor_id, company_id, client_id,
                response_payload, score_payload, summary_payload,
                status, created_at
            ) VALUES (
                :id, :tool_name, :advisor_id, :company_id, :client_id,
                :response_payload, :score_payload, :summary_payload,
                :status, :created_at
            )
        """), {
            "id": session_id,
            "tool_name": payload.tool_name,
            "advisor_id": payload.advisor_id,
            "company_id": payload.company_id,
            "client_id": payload.client_id,
            "response_payload": Json(payload.response_payload),
            "score_payload": Json(payload.score_payload) if payload.score_payload is not None else None,
            "summary_payload": Json(payload.summary_payload) if payload.summary_payload is not None else None,
            "status": "completed",
            "created_at": datetime.utcnow().isoformat()
        })

    return {"ok": True, "id": session_id}



@app.get("/advisor-clients")
def get_advisor_clients(
    current_advisor: dict = Depends(get_current_advisor)
):
    company_id = current_advisor["company_id"]
    advisor_id = current_advisor["advisor_id"]

    query = """
        SELECT id, company_id, advisor_id, first_name, last_name, email, created_at
        FROM clients
        WHERE company_id = :company_id
          AND advisor_id = :advisor_id
        ORDER BY last_name, first_name
    """

    params = {
        "company_id": company_id,
        "advisor_id": advisor_id
    }

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        rows = [dict(row._mapping) for row in result]

    return rows
    

@app.get("/advisor-sessions")
def get_advisor_sessions(current_advisor: dict = Depends(get_current_advisor)):
    advisor_id = current_advisor["advisor_id"]
    company_id = current_advisor["company_id"]
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT ON (cs.client_id, cs.tool_name)
                cs.id,
                cs.tool_name,
                cs.advisor_id,
                cs.company_id,
                cs.client_id,
                c.first_name,
                c.last_name,
                c.email,
                cs.response_payload,
                cs.score_payload,
                cs.summary_payload,
                cs.status,
                cs.created_at
            FROM client_sessions cs
            LEFT JOIN clients c
              ON cs.client_id = c.id
            WHERE cs.advisor_id = :advisor_id
              AND cs.company_id = :company_id
            ORDER BY cs.client_id, cs.tool_name, cs.created_at DESC
        """), {
            "advisor_id": advisor_id,
            "company_id": company_id
        })

        rows = [dict(row._mapping) for row in result]
        return {"sessions": rows}


@app.post("/login")
def advisor_login(payload: AdvisorLogin):
    with engine.connect() as conn:
        advisor = conn.execute(
            text("""
                SELECT id, company_id, email, password_hash, role, is_active
                FROM advisors
                WHERE email = :email
            """),
            {"email": payload.email}
        ).fetchone()

    if not advisor:
        return {"ok": False, "error": "Invalid email or password"}

    advisor = dict(advisor._mapping)

    if not advisor["is_active"]:
        return {"ok": False, "error": "Account is inactive"}

    if not password_hash.verify(payload.password, advisor["password_hash"]):
        return {"ok": False, "error": "Invalid email or password"}
        
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)

    token = jwt.encode(
        {
            "sub": advisor["id"],
            "company_id": advisor["company_id"],
            "role": advisor["role"],
            "exp": expires_at
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )    
        

    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer"
    }   

@app.post("/clients")
def create_client(payload: ClientCreate):
    invite = verify_client_invite_token(payload.invite_token)

    client_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO clients (
                id, company_id, advisor_id, first_name, last_name, email, created_at
            ) VALUES (
                :id, :company_id, :advisor_id, :first_name, :last_name, :email, :created_at
            )
        """), {
            "id": client_id,
            "company_id": invite["company_id"],
            "advisor_id": invite["advisor_id"],
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "email": payload.email,
            "created_at": datetime.utcnow().isoformat()
        })

    return {"ok": True, "client_id": client_id}
