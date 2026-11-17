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
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
DEFAULT_SUBJECTS = (
    ("maths", "Maths", False, 1),
    ("isixhosa", "isiXhosa", False, 2),
    ("english", "English", False, 3),
    ("physics", "Physics", False, 4),
    ("life_orientation", "Life Orientation", False, 5),
    ("optional_1", "Optional subject 1", True, 6),
    ("optional_2", "Optional subject 2", True, 7),
)
bearer_auth = HTTPBearer(auto_error=False)


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
    connection.execute("PRAGMA foreign_keys = ON")
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                subject_key TEXT NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                is_optional INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL,
                UNIQUE (user_id, subject_key),
                UNIQUE (user_id, name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                priority INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                assessment_type TEXT,
                assessment_date TEXT,
                marks_obtained REAL,
                total_marks REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                start_time TEXT NOT NULL,
                end_time TEXT,
                topic TEXT,
                notes TEXT,
                completed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT,
                resource_type TEXT
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
    id: int
    name: str
    is_optional: bool
    position: int


class SubjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Subject name cannot be blank.")
        return normalized


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    due_date: Optional[str] = None
    subject_id: int
    completed: bool = False
    priority: Optional[int] = Field(default=None, ge=1, le=5)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    due_date: Optional[str] = None
    subject_id: Optional[int] = None
    completed: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    due_date: Optional[str] = None
    subject_id: int
    completed: bool = False
    assessment_type: Optional[str] = None
    assessment_date: Optional[str] = None
    marks_obtained: Optional[float] = Field(default=None, ge=0)
    total_marks: Optional[float] = Field(default=None, gt=0)


class AssessmentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = None
    due_date: Optional[str] = None
    subject_id: Optional[int] = None
    completed: Optional[bool] = None
    assessment_type: Optional[str] = None
    assessment_date: Optional[str] = None
    marks_obtained: Optional[float] = Field(default=None, ge=0)
    total_marks: Optional[float] = Field(default=None, gt=0)


class StudySessionCreate(BaseModel):
    subject_id: int
    start_time: str = Field(min_length=1, max_length=64)
    end_time: Optional[str] = None
    topic: Optional[str] = None
    notes: Optional[str] = None
    completed: bool = False


class StudySessionUpdate(BaseModel):
    subject_id: Optional[int] = None
    start_time: Optional[str] = Field(default=None, min_length=1, max_length=64)
    end_time: Optional[str] = None
    topic: Optional[str] = None
    notes: Optional[str] = None
    completed: Optional[bool] = None


class ResourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=2048)
    description: Optional[str] = None
    subject_id: int
    resource_type: Optional[str] = None


class ResourceUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    description: Optional[str] = None
    subject_id: Optional[int] = None
    resource_type: Optional[str] = None


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
    subjects: list[Subject]


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


def public_subject(row: sqlite3.Row) -> Subject:
    return Subject(
        id=row["id"],
        name=row["name"],
        is_optional=bool(row["is_optional"]),
        position=row["position"],
    )


def ensure_default_subjects(connection: sqlite3.Connection, user_id: int) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO subjects (user_id, subject_key, name, is_optional, position)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            (user_id, subject_key, name, int(is_optional), position)
            for subject_key, name, is_optional, position in DEFAULT_SUBJECTS
        ),
    )


def subjects_for_user(connection: sqlite3.Connection, user_id: int) -> list[Subject]:
    rows = connection.execute(
        "SELECT id, name, is_optional, position FROM subjects WHERE user_id = ? ORDER BY position",
        (user_id,),
    ).fetchall()
    return [public_subject(row) for row in rows]


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_auth),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid bearer token is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET_KEY,
            algorithms=["HS256"],
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    with database_connection() as connection:
        row = connection.execute(
            "SELECT id, username, email, full_name, grade FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        raise unauthorized
    return public_user(row)


@app.get("/")
async def root():
    return {
        "message": "Welcome to the Matric Planner Application API!",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "users": "/users/me",
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


@app.get("/users/me", response_model=User)
def get_my_profile(current_user: User = Depends(get_current_user)) -> User:
    return current_user


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
            ensure_default_subjects(connection, cursor.lastrowid)
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

    with database_connection() as connection:
        ensure_default_subjects(connection, row["id"])
        subjects = subjects_for_user(connection, row["id"])

    return TokenResponse(
        access_token=create_access_token(row["id"]),
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        user=public_user(row),
        subjects=subjects,
    )


@app.get("/subjects", response_model=list[Subject])
def get_subjects(current_user: User = Depends(get_current_user)) -> list[Subject]:
    with database_connection() as connection:
        ensure_default_subjects(connection, current_user.id)
        return subjects_for_user(connection, current_user.id)


@app.patch("/subjects/{subject_id}", response_model=Subject)
def rename_optional_subject(
    subject_id: int,
    request: SubjectUpdate,
    current_user: User = Depends(get_current_user),
) -> Subject:
    with database_connection() as connection:
        row = connection.execute(
            "SELECT subject_key FROM subjects WHERE id = ? AND user_id = ?",
            (subject_id, current_user.id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subject not found.",
            )
        if not row["subject_key"].startswith("optional_"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only optional subjects can be renamed.",
            )

        try:
            connection.execute(
                "UPDATE subjects SET name = ? WHERE id = ? AND user_id = ?",
                (request.name, subject_id, current_user.id),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That subject name is already in your list.",
            ) from None

        updated_row = connection.execute(
            "SELECT id, name, is_optional, position FROM subjects WHERE id = ?",
            (subject_id,),
        ).fetchone()
    return public_subject(updated_row)


ENTITY_FIELDS = {
    "tasks": (
        "title", "description", "due_date", "subject_id", "completed", "priority"
    ),
    "assessments": (
        "title", "description", "due_date", "subject_id", "completed",
        "assessment_type", "assessment_date", "marks_obtained", "total_marks",
    ),
    "study_sessions": (
        "subject_id", "start_time", "end_time", "topic", "notes", "completed"
    ),
    "resources": (
        "title", "url", "description", "subject_id", "resource_type"
    ),
}
ENTITY_REQUIRED_FIELDS = {
    "tasks": {"title", "subject_id", "completed"},
    "assessments": {"title", "subject_id", "completed"},
    "study_sessions": {"subject_id", "start_time", "completed"},
    "resources": {"title", "url", "subject_id"},
}


def _entity_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Record not found.",
    )


def _ensure_subject_belongs_to_user(
    connection: sqlite3.Connection,
    subject_id: int,
    user_id: int,
) -> None:
    row = connection.execute(
        "SELECT 1 FROM subjects WHERE id = ? AND user_id = ?",
        (subject_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject not found.",
        )


def _entity_output(row: sqlite3.Row) -> dict:
    result = dict(row)
    if "completed" in result:
        result["completed"] = bool(result["completed"])
    return result


def _list_entities(
    table: str,
    user_id: int,
    subject_id: Optional[int] = None,
) -> list[dict]:
    with database_connection() as connection:
        if subject_id is not None:
            _ensure_subject_belongs_to_user(connection, subject_id, user_id)
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE user_id = ? AND subject_id = ? ORDER BY id DESC",
                (user_id, subject_id),
            ).fetchall()
        else:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
    return [_entity_output(row) for row in rows]


def _create_entity(table: str, values: dict, user_id: int) -> dict:
    fields = ENTITY_FIELDS[table]
    with database_connection() as connection:
        _ensure_subject_belongs_to_user(connection, values["subject_id"], user_id)
        insert_fields = ("user_id", *fields)
        insert_values = (user_id, *(int(values[name]) if name == "completed" else values[name] for name in fields))
        placeholders = ", ".join("?" for _ in insert_fields)
        cursor = connection.execute(
            f"INSERT INTO {table} ({', '.join(insert_fields)}) VALUES ({placeholders})",
            insert_values,
        )
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
            (cursor.lastrowid, user_id),
        ).fetchone()
    return _entity_output(row)


def _get_entity(table: str, record_id: int, user_id: int) -> dict:
    with database_connection() as connection:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()
    if row is None:
        raise _entity_not_found()
    return _entity_output(row)


def _update_entity(table: str, record_id: int, values: dict, user_id: int) -> dict:
    values = {key: value for key, value in values.items() if key in ENTITY_FIELDS[table]}
    if not values:
        return _get_entity(table, record_id, user_id)

    with database_connection() as connection:
        existing = connection.execute(
            f"SELECT id FROM {table} WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()
        if existing is None:
            raise _entity_not_found()

        if "subject_id" in values:
            if values["subject_id"] is None:
                raise HTTPException(status_code=422, detail="subject_id cannot be null.")
            _ensure_subject_belongs_to_user(connection, values["subject_id"], user_id)

        for field in ENTITY_REQUIRED_FIELDS[table]:
            if field in values and values[field] is None:
                raise HTTPException(status_code=422, detail=f"{field} cannot be null.")

        assignments = ", ".join(f"{field} = ?" for field in values)
        parameters = tuple(
            int(value) if field == "completed" and value is not None else value
            for field, value in values.items()
        )
        connection.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ? AND user_id = ?",
            (*parameters, record_id, user_id),
        )
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()
    return _entity_output(row)


def _delete_entity(table: str, record_id: int, user_id: int) -> None:
    with database_connection() as connection:
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        )
        if cursor.rowcount == 0:
            raise _entity_not_found()


@app.get("/tasks", response_model=list[Task])
def get_tasks(
    subject_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return _list_entities("tasks", current_user.id, subject_id)


@app.post("/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(request: TaskCreate, current_user: User = Depends(get_current_user)) -> dict:
    return _create_entity("tasks", request.model_dump(), current_user.id)


@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: int, current_user: User = Depends(get_current_user)) -> dict:
    return _get_entity("tasks", task_id, current_user.id)


@app.patch("/tasks/{task_id}", response_model=Task)
def update_task(
    task_id: int,
    request: TaskUpdate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _update_entity("tasks", task_id, request.model_dump(exclude_unset=True), current_user.id)


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, current_user: User = Depends(get_current_user)) -> Response:
    _delete_entity("tasks", task_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/assessments", response_model=list[Assessment])
def get_assessments(
    subject_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return _list_entities("assessments", current_user.id, subject_id)


@app.post("/assessments", response_model=Assessment, status_code=status.HTTP_201_CREATED)
def create_assessment(
    request: AssessmentCreate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _create_entity("assessments", request.model_dump(), current_user.id)


@app.get("/assessments/{assessment_id}", response_model=Assessment)
def get_assessment(
    assessment_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _get_entity("assessments", assessment_id, current_user.id)


@app.patch("/assessments/{assessment_id}", response_model=Assessment)
def update_assessment(
    assessment_id: int,
    request: AssessmentUpdate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _update_entity(
        "assessments", assessment_id, request.model_dump(exclude_unset=True), current_user.id
    )


@app.delete("/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assessment(
    assessment_id: int,
    current_user: User = Depends(get_current_user),
) -> Response:
    _delete_entity("assessments", assessment_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/study-sessions", response_model=list[StudySession])
def get_study_sessions(
    subject_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return _list_entities("study_sessions", current_user.id, subject_id)


@app.post("/study-sessions", response_model=StudySession, status_code=status.HTTP_201_CREATED)
def create_study_session(
    request: StudySessionCreate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _create_entity("study_sessions", request.model_dump(), current_user.id)


@app.get("/study-sessions/{study_session_id}", response_model=StudySession)
def get_study_session(
    study_session_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _get_entity("study_sessions", study_session_id, current_user.id)


@app.patch("/study-sessions/{study_session_id}", response_model=StudySession)
def update_study_session(
    study_session_id: int,
    request: StudySessionUpdate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _update_entity(
        "study_sessions", study_session_id, request.model_dump(exclude_unset=True), current_user.id
    )


@app.delete("/study-sessions/{study_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_study_session(
    study_session_id: int,
    current_user: User = Depends(get_current_user),
) -> Response:
    _delete_entity("study_sessions", study_session_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/resources", response_model=list[Resource])
def get_resources(
    subject_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return _list_entities("resources", current_user.id, subject_id)


@app.post("/resources", response_model=Resource, status_code=status.HTTP_201_CREATED)
def create_resource(
    request: ResourceCreate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _create_entity("resources", request.model_dump(), current_user.id)


@app.get("/resources/{resource_id}", response_model=Resource)
def get_resource(resource_id: int, current_user: User = Depends(get_current_user)) -> dict:
    return _get_entity("resources", resource_id, current_user.id)


@app.patch("/resources/{resource_id}", response_model=Resource)
def update_resource(
    resource_id: int,
    request: ResourceUpdate,
    current_user: User = Depends(get_current_user),
) -> dict:
    return _update_entity("resources", resource_id, request.model_dump(exclude_unset=True), current_user.id)


@app.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(resource_id: int, current_user: User = Depends(get_current_user)) -> Response:
    _delete_entity("resources", resource_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
