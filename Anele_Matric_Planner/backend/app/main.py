import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import jwt
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator


DATABASE_PATH = Path(
    os.getenv(
        "MATRIC_PLANNER_DB_PATH",
        str(Path(__file__).resolve().with_name("matric_planner.db")),
    )
)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(32)
ACCESS_TOKEN_TTL_SECONDS = 30 * 60
PASSWORD_HASH_ITERATIONS = 600_000
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


app = FastAPI(
    title="Matric Planner Application",
    description="This is a backend API for the Matric Planner Application.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def database_connection() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with database_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                full_name TEXT,
                grade INTEGER NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )


initialize_database()


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(min_length=3, max_length=254)
    full_name: Optional[str] = Field(default=None, max_length=100)
    grade: int
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LoginRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=254)
    email: Optional[str] = Field(default=None, min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_login_identifier(self) -> "LoginRequest":
        if not self.username and not self.email:
            raise ValueError("Provide a username or email address.")
        return self

    @field_validator("username", "email")
    @classmethod
    def normalize_identifier(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().lower() if value else value


class User(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    grade: int


class Subject(BaseModel):
    name: str
    user_id: int
    target_grade: int
    current_grade: int
    color: Optional[str] = None
    description: Optional[str] = None


class Task(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    subject_id: int
    user_id: int
    completed: bool = False
    priority: Optional[int] = None


class Assessment(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    subject_id: int
    user_id: int
    completed: bool = False
    assessment_type: Optional[str] = None
    assessment_date: Optional[str] = None
    marks_obtained: Optional[float] = None
    total_marks: Optional[float] = None


class StudySession(BaseModel):
    subject_id: int
    user_id: int
    start_time: str
    end_time: Optional[str] = None
    topic: Optional[str] = None
    notes: Optional[str] = None
    completed: bool = False


class Resource(BaseModel):
    title: str
    url: str
    description: Optional[str] = None
    subject_id: int
    user_id: int
    resource_type: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: User


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PASSWORD_HASH_ITERATIONS),
            _encode_base64url(salt),
            _encode_base64url(password_hash),
        )
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_hash = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _decode_base64url(encoded_salt),
            int(iterations),
        )
        return hmac.compare_digest(candidate_hash, _decode_base64url(encoded_hash))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    issued_at = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": issued_at + ACCESS_TOKEN_TTL_SECONDS,
        },
        JWT_SECRET_KEY,
        algorithm="HS256",
    )


def public_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        full_name=row["full_name"],
        grade=row["grade"],
    )


@app.get("/")
async def root():
    return {
        "message": "Welcome to the Matric Planner Application API!",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "users": "/users",
            "login": "/auth/login",
            "register": "/auth/register",
            "subjects": "/subjects",
            "subject": "/subjects/{subject_id}",
            "tasks": "/tasks",
            "task": "/tasks/{task_id}",
            "assessments": "/assessments",
            "assessment": "/assessments/{assessment_id}",
            "study_sessions": "/study-sessions",
            "study_session": "/study-sessions/{study_session_id}",
            "resources": "/resources",
            "resource": "/resources/{resource_id}",
        },
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post(
    "/auth/register",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
)
def register_user(request: RegisterRequest) -> User:
    with database_connection() as connection:
        existing_user = connection.execute(
            "SELECT 1 FROM users WHERE username = ? OR email = ?",
            (request.username, request.email),
        ).fetchone()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with that username or email already exists.",
            )

        try:
            cursor = connection.execute(
                """
                INSERT INTO users (username, email, full_name, grade, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.username,
                    request.email,
                    request.full_name,
                    request.grade,
                    hash_password(request.password),
                    int(time.time()),
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with that username or email already exists.",
            ) from None

        row = connection.execute(
            "SELECT id, username, email, full_name, grade FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return public_user(row)


@app.post("/auth/login", response_model=TokenResponse)
def login_user(request: LoginRequest) -> TokenResponse:
    if request.username:
        lookup_column = "username"
        identifier = request.username
    else:
        lookup_column = "email"
        identifier = request.email

    with database_connection() as connection:
        row = connection.execute(
            f"SELECT * FROM users WHERE {lookup_column} = ?",
            (identifier,),
        ).fetchone()

    if row is None or not verify_password(request.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=create_access_token(row["id"]),
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        user=public_user(row),
    )
