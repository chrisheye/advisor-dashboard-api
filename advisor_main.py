from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
from sqlalchemy import create_engine, text, MetaData, Table, Column, String, JSON
from psycopg2.extras import Json

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/create-client-sessions-table")
def create_client_sessions_table():
    metadata.create_all(engine)
    return {"ok": True, "table": "client_sessions"}


@app.get("/db-test")
def db_test():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        return {"ok": result.scalar() == 1}


# --- ROUTES ---

import json
import uuid
from datetime import datetime

@app.get("/insert-test-session")
def insert_test_session():
    test_id = str(uuid.uuid4())

    response_payload = {
        "q1": 4, "q2": 2, "q3": 5, "q4": 3, "q5": 4,
        "q6": 2, "q7": 5, "q8": 3, "q9": 4, "q10": 2
    }

    score_payload = {
        "persona": "Income Seeker",
        "protected_income_fit": "high",
        "risk_exposure": "Moderate–High",
        "readiness": "Ready for Discussion",
        "key_drivers": ["High Longevity Risk", "Low Income Stability"],
        "radar_scores": {
            "longevity": 84,
            "income_stability": 76,
            "market_risk": 58,
            "health": 52,
            "behavioral": 44
        }
    }

    summary_payload = {
        "persona_description": "Focused on creating more reliable retirement income and reducing uncertainty.",
        "fit_label": "Strong Candidate",
        "fit_headline": "Strong Candidate for Protected Income Strategies",
        "fit_explanation": "Driven by high longevity risk and low income stability.",
        "radar_caption": "This profile shows elevated longevity risk and income instability, suggesting a need for more predictable income sources.",
        "talking_points": [
            {"label": "Open", "text": "How are you thinking about income over what could be a long retirement horizon?"},
            {"label": "Explore", "text": "How comfortable would you feel if markets were down for several years while you were drawing income?"},
            {"label": "Introduce", "text": "Would you be open to exploring ways to create more predictable income as part of your broader retirement plan?"}
        ],
        "playbook_intro": "This playbook is designed for clients with high longevity risk and low income stability.",
        "playbook_steps": [
            "Introduce income stability as a planning priority.",
            "Explore comfort with market-based income.",
            "Present protected income as an option rather than a product pitch."
        ]
    }

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
            "id": test_id,
            "tool_name": "annuity_puzzle_solver",
            "advisor_id": "advisor_1",
            "company_id": "company_a",
            "client_id": "client_1",
            "response_payload": Json(response_payload),
            "score_payload": Json(score_payload),
            "summary_payload": Json(summary_payload),
            "status": "completed",
            "created_at": datetime.utcnow().isoformat()
        })

    return {"ok": True, "id": test_id}


@app.get("/")
def root():
    return {"message": "advisor backend is running"}


@app.get("/debug-client-sessions-columns")
def debug_client_sessions_columns():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'client_sessions'
            ORDER BY ordinal_position
        """))
        columns = [row[0] for row in result]
        return {"columns": columns}

@app.get("/reset-client-sessions-table")
def reset_client_sessions_table():
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS client_sessions"))
    metadata.create_all(engine)
    return {"ok": True, "reset": True}

import json

@app.get("/get-sessions")
def get_sessions():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM client_sessions"))
        rows = [dict(row._mapping) for row in result]
        return {"sessions": rows}

@app.get("/migrate-client-sessions-to-jsonb")
def migrate_client_sessions_to_jsonb():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE client_sessions
            ALTER COLUMN response_payload TYPE jsonb USING response_payload::jsonb,
            ALTER COLUMN score_payload TYPE jsonb USING score_payload::jsonb,
            ALTER COLUMN summary_payload TYPE jsonb USING summary_payload::jsonb
        """))
    return {"ok": True, "migrated": True}

@app.get("/delete-all-sessions")
def delete_all_sessions():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM client_sessions"))
    return {"ok": True, "deleted": True}


@app.get("/advisor-clients")
def get_advisor_clients(
    company_id: str | None = None,
    advisor_id: str | None = None
):
    filtered_clients = DEMO_CLIENTS

    if company_id is not None:
        filtered_clients = [
            client for client in filtered_clients
            if client["company_id"] == company_id
        ]

    if advisor_id is not None:
        filtered_clients = [
            client for client in filtered_clients
            if client["advisor_id"] == advisor_id
        ]

    return filtered_clients
    if company_id is None:
        return DEMO_CLIENTS

    filtered_clients = [
        client for client in DEMO_CLIENTS
        if client["company_id"] == company_id
    ]
    return filtered_clients
