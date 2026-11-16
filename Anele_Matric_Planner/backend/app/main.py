from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Matric Planner Application",
    description="This is a backend API for the Matric Planner Application.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to the Matric Planner Application API!",
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
                "resource": "/resources/{resource_id}"

            }
            }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

class User(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    grade: int
    password_hash: str

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

