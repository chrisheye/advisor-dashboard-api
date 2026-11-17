from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from sqlalchemy import create_engine, text, MetaData, Table, Column, String, JSON, Boolean, DateTime, UniqueConstraint
from psycopg2.extras import Json
from pwdlib import PasswordHash
import jwt
import json
import uuid
import secrets
import hashlib
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from pydantic import EmailStr, Field
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Header, HTTPException, Depends, Request, Response


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
    Column("invite_id", String, nullable=True, unique=True),
    Column("first_name", String, nullable=False),
    Column("last_name", String, nullable=False),
    Column("email", String, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
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

# The token table is additive; existing client and assessment tables are unchanged.
auth_links = Table(
    "client_auth_links", metadata,
    Column("id", String, primary_key=True),
    Column("token_hash", String, nullable=False, unique=True),
    Column("purpose", String, nullable=False),  # invite or login
    Column("email", String, nullable=False),
    Column("first_name", String, nullable=True),
    Column("last_name", String, nullable=True),
    Column("company_id", String, nullable=False),
    Column("advisor_id", String, nullable=False),
    Column("client_id", String, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
# Server-side revocable client sessions. A token is never stored in plaintext.
client_login_sessions = Table(
    "client_login_sessions", metadata,
    Column("id", String, primary_key=True),
    Column("token_hash", String, nullable=False, unique=True),
    Column("client_id", String, nullable=False),
    Column("advisor_id", String, nullable=False),
    Column("company_id", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)
metadata.create_all(engine, tables=[advisors, auth_links, client_login_sessions])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.whealthchat.ai",
        "https://demo.whealthchat.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required")


class ClientSessionCreate(BaseModel):
    tool_name: str
    response_payload: dict
    score_payload: dict | None = None
    summary_payload: dict | None = None

    class Config:
        extra = "forbid"

class ClientCreate(BaseModel):
    invite_token: str
    first_name: str
    last_name: str
    email: str

class EmailClientInvite(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr

class AdvisorResendInvitation(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)

class ClientLoginRequest(BaseModel):
    email: EmailStr

class ClientLinkVerify(BaseModel):
    token: str = Field(min_length=20, max_length=200)

class AdvisorLogin(BaseModel):
    email: str
    password: str

def get_current_advisor(request: Request):
    token = request.cookies.get("advisor_access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Advisor session required")

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

    if payload.get("role") != "advisor":
        raise HTTPException(status_code=403, detail="Advisor access required")

    with engine.connect() as conn:
        advisor = conn.execute(
            text("""
                SELECT is_active
                FROM advisors
                WHERE id = :advisor_id
                  AND company_id = :company_id
            """),
            {
                "advisor_id": payload["sub"],
                "company_id": payload["company_id"]
            }
        ).fetchone()

    if not advisor or not advisor.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account is inactive"
        )

    return {
        "advisor_id": payload["sub"],
        "company_id": payload["company_id"],
        "role": payload["role"]
    }
    
def create_client_invite_token(advisor_id: str, company_id: str):
    invite_id = str(uuid.uuid4())

    return jwt.encode(
        {
            "advisor_id": advisor_id,
            "company_id": company_id,
            "type": "client_invite",
            "invite_id": invite_id
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )

class ClientInviteAccess(BaseModel):
    invite_token: str


# --- ROUTES ---
 
# Legacy unverified invite endpoints are intentionally disabled in v2.
# Deploy the matching client/advisor frontend before activating this backend.
@app.post("/client-invite", status_code=410)
def legacy_client_invite_disabled():
    raise HTTPException(status_code=410, detail="Use /client-invitations")

# Every authenticated visit extends expiry by 30 days. Sessions remain valid
# indefinitely with regular activity, unless revoked or the client is deactivated.
CLIENT_IDLE_DAYS = 30
CLIENT_COOKIE_MAX_AGE = CLIENT_IDLE_DAYS * 24 * 60 * 60


def _client_session_cookie(response: Response, raw_token: str):
    response.set_cookie(
        "client_access_token", raw_token, httponly=True, secure=True,
        samesite="lax", max_age=CLIENT_COOKIE_MAX_AGE, path="/",
    )


def _create_client_session(response: Response, client_id: str, advisor_id: str, company_id: str):
    raw_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(client_login_sessions.insert().values(
            id=str(uuid.uuid4()),
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            client_id=client_id, advisor_id=advisor_id, company_id=company_id,
            created_at=now, last_seen_at=now,
            expires_at=now + timedelta(days=CLIENT_IDLE_DAYS), revoked_at=None,
        ))
    _client_session_cookie(response, raw_token)


def get_current_client(request: Request, response: Response):
    raw_token = request.cookies.get("client_access_token")
    if not raw_token:
        raise HTTPException(status_code=401, detail="Client session required")

    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    with engine.begin() as conn:
        # Lock the row to serialize validation, renewal and logout.
        session = conn.execute(text("""
            SELECT s.client_id, s.advisor_id, s.company_id, c.is_active
              FROM client_login_sessions s
              JOIN clients c ON c.id = s.client_id
               AND c.advisor_id = s.advisor_id AND c.company_id = s.company_id
             WHERE s.token_hash = :digest AND s.revoked_at IS NULL
               AND s.expires_at > :now
             FOR UPDATE OF s
        """), {"digest": digest, "now": now}).mappings().first()
        if not session or not session["is_active"]:
            raise HTTPException(status_code=401, detail="Client session expired or revoked")
        conn.execute(text("""
            UPDATE client_login_sessions
               SET last_seen_at = :now, expires_at = :expires_at
             WHERE token_hash = :digest
        """), {"now": now, "expires_at": now + timedelta(days=CLIENT_IDLE_DAYS),
               "digest": digest})

    # Refresh the browser cookie too; updating the DB alone is insufficient.
    _client_session_cookie(response, raw_token)
    return {"client_id": session["client_id"],
            "advisor_id": session["advisor_id"],
            "company_id": session["company_id"]}


@app.get("/")
def root():
    return {"message": "advisor backend is running"}

@app.post("/client-sessions")
def create_client_session(
    payload: ClientSessionCreate,
    current_client: dict = Depends(get_current_client)
):
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
            "advisor_id": current_client["advisor_id"],
            "company_id": current_client["company_id"],
            "client_id": current_client["client_id"],
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
        SELECT id, company_id, advisor_id, first_name, last_name, email, is_active, created_at
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
    

@app.get("/client-sessions/me")
def get_client_sessions(
    current_client: dict = Depends(get_current_client)
):
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT *
                FROM client_sessions
                WHERE client_id = :client_id
                  AND advisor_id = :advisor_id
                  AND company_id = :company_id
                ORDER BY created_at DESC
            """),
            {
                "client_id": current_client["client_id"],
                "advisor_id": current_client["advisor_id"],
                "company_id": current_client["company_id"]
            }
        ).fetchall()

    return [dict(row._mapping) for row in rows]


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
def advisor_login(payload: AdvisorLogin, response: Response):
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
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    advisor = dict(advisor._mapping)

    if not advisor["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="Account is inactive"
        )

    if not password_hash.verify(payload.password, advisor["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
        
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
    
    response.set_cookie(
    key="advisor_access_token",
    value=token,
    httponly=True,
    secure=True,
    samesite="lax",
    max_age=JWT_EXPIRE_MINUTES * 60
    )    

    return {
        "ok": True
    } 

@app.post("/clients", status_code=410)
def legacy_client_creation_disabled():
    raise HTTPException(status_code=410, detail="Use /client-auth/verify-link")

@app.post("/client-invite-access", status_code=410)
def legacy_invite_access_disabled():
    raise HTTPException(status_code=410, detail="Use /client-auth/verify-link")


# -----------------------------------------------------------------------------
# CLIENT EMAIL INVITATIONS AND PASSWORDLESS LOGIN (v2)
# Environment variables: RESEND_API_KEY, RESEND_FROM,
# CLIENT_APP_URL (the client bot's public HTTPS URL).
# Email links go to the CLIENT_APP_URL; its frontend must POST the token to
# /client-auth/verify-link and then remove it from the browser address bar.
# -----------------------------------------------------------------------------

INVITE_TTL_HOURS = 48
LOGIN_TTL_MINUTES = 15
CLIENT_APP_URL = os.getenv("CLIENT_APP_URL", "").strip()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _new_link(purpose: str, email: str, company_id: str, advisor_id: str,
              first_name: str | None = None, last_name: str | None = None,
              client_id: str | None = None) -> str:
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=INVITE_TTL_HOURS) if purpose == "invite" else timedelta(minutes=LOGIN_TTL_MINUTES)
    with engine.begin() as conn:
        conn.execute(auth_links.insert().values(
            id=str(uuid.uuid4()),
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            purpose=purpose, email=_normalize_email(email),
            company_id=company_id, advisor_id=advisor_id,
            first_name=first_name, last_name=last_name,
            client_id=client_id, created_at=now, expires_at=now + ttl,
            consumed_at=None,
        ))
    return raw


def _send_auth_email(email: str, token: str, purpose: str,
                     additional_tokens: list[str] | None = None,
                     account_labels: list[str] | None = None):
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("RESEND_FROM", "").strip()
    if not CLIENT_APP_URL.startswith("https://") or not api_key or not sender:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")

    from urllib.parse import urlsplit, urlunsplit, parse_qsl
    parsed = urlsplit(CLIENT_APP_URL)
    params = dict(parse_qsl(parsed.query))
    params["auth_token"] = token
    link = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ""))
    subject = "Your WhealthChat invitation" if purpose == "invite" else "Your WhealthChat sign-in link"
    verb = "Finish setting up your account" if purpose == "invite" else "Sign in to your account"
    ttl = "48 hours" if purpose == "invite" else "15 minutes"
    if purpose == "login" and additional_tokens:
        all_links = [link]
        for extra_token in additional_tokens:
            extra_params = dict(parse_qsl(parsed.query))
            extra_params["auth_token"] = extra_token
            all_links.append(urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                         urlencode(extra_params), "")))
        # Identify multiple client profiles by advisor and creation date instead
        # of anonymous "Account 1 / Account 2" labels.
        numbered_links = "\n\n".join(
            f"{(account_labels[i] if account_labels and i < len(account_labels) else f'Account {i + 1}')}: {item}"
            for i, item in enumerate(all_links)
        )
        body = ("Your email address is associated with multiple WhealthChat client accounts. "
                "Choose the link for the account you want to access:\n\n"
                f"{numbered_links}\n\nEach link expires in {ttl} and works only once. "
                "If you did not request this, you can ignore this message.\n")
    else:
        body = (f"{verb} using this secure, one-time link:\n\n{link}\n\n"
                f"This link expires in {ttl}. If you did not request it, you can ignore this message.\n")
    request_body = json.dumps({
        "from": sender,
        "to": [email],
        "subject": subject,
        "text": body,
    }).encode("utf-8")
    request = UrlRequest(
        "https://api.resend.com/emails",
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "WhealthChat-Auth/2.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as result:
            if result.status not in (200, 201, 202):
                raise HTTPException(status_code=503, detail="Unable to send email")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        # Do not log the access token, sign-in URL, or API key.
        logging.error("Resend email delivery failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Unable to send email") from exc


def _set_client_cookie(response: Response, client_id: str, advisor_id: str, company_id: str):
    _create_client_session(response, client_id, advisor_id, company_id)


@app.post("/client-invitations", status_code=202)
def send_client_invitation(payload: EmailClientInvite,
                           current_advisor: dict = Depends(get_current_advisor)):
    # Authenticate the advisor; only the server chooses firm and advisor IDs.
    email = _normalize_email(str(payload.email))
    with engine.connect() as conn:
        # An existing client under the same advisor keeps their original client_id.
        existing = conn.execute(text("""
            SELECT id FROM clients WHERE lower(email) = :email
              AND company_id = :company_id AND advisor_id = :advisor_id
              AND is_active = true ORDER BY created_at LIMIT 1
        """), {"email": email, "company_id": current_advisor["company_id"],
               "advisor_id": current_advisor["advisor_id"]}).first()
    if existing:
        token = _new_link("login", email, current_advisor["company_id"],
                          current_advisor["advisor_id"], client_id=existing.id)
        _send_auth_email(email, token, "login")
        return {"ok": True, "message": "Existing client sign-in link sent"}
    token = _new_link("invite", email,
                      current_advisor["company_id"], current_advisor["advisor_id"],
                      payload.first_name.strip(), payload.last_name.strip())
    _send_auth_email(email, token, "invite")
    return {"ok": True, "message": "Invitation email sent"}


@app.post("/advisor-clients/resend-invitation", status_code=202)
def advisor_resend_invitation(payload: AdvisorResendInvitation,
                              current_advisor: dict = Depends(get_current_advisor)):
    # Select the recipient solely from the authenticated advisor's own records.
    with engine.connect() as conn:
        client = conn.execute(text("""
            SELECT id, email FROM clients
             WHERE id = :client_id AND advisor_id = :advisor_id
               AND company_id = :company_id AND is_active = true
        """), {"client_id": payload.client_id,
                "advisor_id": current_advisor["advisor_id"],
                "company_id": current_advisor["company_id"]}).mappings().first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        # Limit repeated email requests for this client; avoid rapid accidental resends.
        recent = conn.execute(text("""
            SELECT 1 FROM client_auth_links
             WHERE client_id = :client_id AND purpose = 'login'
               AND created_at > :cutoff LIMIT 1
        """), {"client_id": client["id"],
                "cutoff": datetime.now(timezone.utc) - timedelta(seconds=60)}).first()
        if recent:
            raise HTTPException(status_code=429,
                                detail="A sign-in link was sent recently. Please wait a minute before resending.")
    token = _new_link("login", client["email"], current_advisor["company_id"],
                      current_advisor["advisor_id"], client_id=client["id"])
    _send_auth_email(client["email"], token, "login")
    return {"ok": True, "message": "Sign-in link sent"}


@app.post("/client-auth/request-link", status_code=202)
def request_client_sign_in(payload: ClientLoginRequest):
    # Identical public response whether or not email belongs to a client.
    email = _normalize_email(str(payload.email))
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.advisor_id, c.company_id, c.first_name, c.last_name,
                   c.created_at, a.email AS advisor_email
              FROM clients c LEFT JOIN advisors a ON a.id = c.advisor_id
             WHERE lower(c.email) = :email AND c.is_active = true
             ORDER BY c.created_at, c.id
        """), {"email": email}).fetchall()
    # Basic per-email throttling. Also enforce IP-based throttling at the edge
    # before opening this public endpoint to the internet.
    with engine.connect() as conn:
        recent = conn.execute(text("""
            SELECT 1 FROM client_auth_links
            WHERE purpose = 'login' AND email = :email
              AND created_at > :cutoff LIMIT 1
        """), {"email": email, "cutoff": datetime.now(timezone.utc) - timedelta(seconds=60)}).first()
    if recent:
        return {"ok": True, "message": "If an account exists, a sign-in link will be emailed"}
    tokens = [
        _new_link("login", email, row.company_id, row.advisor_id, client_id=row.id)
        for row in rows
    ]
    if tokens:
        # Send a single email even when the address belongs to more than one
        # client record. Keep distinct account links rather than guessing which
        # advisor/client identity should be used.
        labels = [
            f"Advisor {row.advisor_email or 'not listed'} — "
            f"{row.first_name} {row.last_name} — Created {str(row.created_at)[:10]}"
            for row in rows
        ]
        _send_auth_email(email, tokens[0], "login", additional_tokens=tokens[1:],
                         account_labels=labels)
    return {"ok": True, "message": "If an account exists, a sign-in link will be emailed"}


@app.post("/client-auth/verify-link")
def verify_client_link(payload: ClientLinkVerify, response: Response):
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(payload.token.encode()).hexdigest()
    # Atomic one-time redemption. A token is marked consumed even if an account
    # has since been deactivated; a second redemption is never accepted.
    with engine.begin() as conn:
        link = conn.execute(text("""
            UPDATE client_auth_links
               SET consumed_at = :now
             WHERE token_hash = :digest AND consumed_at IS NULL AND expires_at > :now
         RETURNING purpose, email, first_name, last_name, company_id, advisor_id, client_id
        """), {"digest": digest, "now": now}).mappings().first()
        if not link:
            raise HTTPException(status_code=401, detail="Link expired or already used")

        if link["purpose"] == "invite":
            # Serialize registration for this advisor and email. FOR UPDATE on
            # an existing row alone cannot lock the absence of a client record.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {
                "key": "client:" + link["company_id"] + ":" + link["advisor_id"] + ":" + link["email"]
            })
            # Email ownership is proved by receiving the invitation in that inbox.
            # Reuse an existing identity for this advisor rather than duplicate it.
            existing = conn.execute(text("""
                SELECT id, is_active FROM clients
                 WHERE lower(email) = :email AND company_id = :company_id
                   AND advisor_id = :advisor_id
                 ORDER BY created_at LIMIT 1 FOR UPDATE
            """), {"email": link["email"], "company_id": link["company_id"],
                   "advisor_id": link["advisor_id"]}).mappings().first()
            if existing:
                if not existing["is_active"]:
                    raise HTTPException(status_code=403, detail="Client access is inactive")
                client_id = existing["id"]
            else:
                client_id = str(uuid.uuid4())
                conn.execute(text("""
                    INSERT INTO clients (id, company_id, advisor_id, first_name, last_name,
                                         email, is_active, created_at)
                    VALUES (:id, :company_id, :advisor_id, :first_name, :last_name,
                            :email, true, :created_at)
                """), {"id": client_id, "company_id": link["company_id"],
                       "advisor_id": link["advisor_id"],
                       "first_name": link["first_name"], "last_name": link["last_name"],
                       "email": link["email"], "created_at": now.isoformat()})
        else:
            client_id = link["client_id"]
            active = conn.execute(text("""
                SELECT 1 FROM clients WHERE id = :id AND company_id = :company_id
                  AND advisor_id = :advisor_id AND is_active = true
            """), {"id": client_id, "company_id": link["company_id"],
                   "advisor_id": link["advisor_id"]}).first()
            if not active:
                raise HTTPException(status_code=403, detail="Client access is inactive")

    _set_client_cookie(response, client_id, link["advisor_id"], link["company_id"])
    return {"ok": True, "client_id": client_id,
            "company_id": link["company_id"], "advisor_id": link["advisor_id"]}


@app.get("/client-auth/me")
def client_session_status(current_client: dict = Depends(get_current_client)):
    # Return the display name only for the authenticated client identity.
    with engine.connect() as conn:
        client = conn.execute(text("""
            SELECT first_name, last_name FROM clients
             WHERE id = :client_id AND advisor_id = :advisor_id
               AND company_id = :company_id AND is_active = true
        """), current_client).mappings().first()
    if not client:
        raise HTTPException(status_code=401, detail="Client session invalid")
    return {"ok": True, **current_client,
            "first_name": client["first_name"], "last_name": client["last_name"]}


@app.post("/client-auth/logout")
def client_logout(request: Request, response: Response):
    raw = request.cookies.get("client_access_token")
    if raw:
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE client_login_sessions SET revoked_at = :now
                WHERE token_hash = :digest AND revoked_at IS NULL
            """), {"now": datetime.now(timezone.utc), "digest": digest})
    response.delete_cookie("client_access_token", path="/", secure=True, httponly=True, samesite="lax")
    return {"ok": True}
