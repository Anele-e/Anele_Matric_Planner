# Matric Planner API

The backend is a FastAPI application. It stores users, subjects, tasks,
assessments, study sessions, and resources in SQLite at
`backend/app/matric_planner.db` by default; set `MATRIC_PLANNER_DB_PATH` to use a
different database file.

## Run the backend

From this directory, install the dependencies and start the development server:

```bash
pip install -r requirements.txt
export JWT_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn backend.app.main:app --reload
```

Keep `JWT_SECRET_KEY` stable between restarts so existing access tokens remain
valid. If it is omitted, the server creates a temporary key for that process.
The interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Authentication

Register with `POST /auth/register`:

```json
{
  "username": "anelee",
  "email": "anele@example.com",
  "full_name": "Anele E",
  "grade": 12,
  "password": "a-long-password"
}
```

The response contains the public profile only. Passwords are hashed by the
server and are never returned. Duplicate usernames or email addresses return
`409 Conflict`.

Log in with `POST /auth/login`, providing either `email` or `username` with the
password. A successful login returns a 30-minute bearer token, the public
profile, and the student's subjects. Invalid credentials return `401
Unauthorized`.

Each account starts with Maths, isiXhosa, English, Physics, Life Orientation,
and two optional subject slots. `GET /subjects` returns the saved list for the
authenticated user; `PATCH /subjects/{subject_id}` renames an optional subject.
`GET /users/me` returns the authenticated user's public profile.

## Planner endpoints

The following routes require the bearer token returned by `/auth/login`:

| Record | Collection | Single record |
| --- | --- | --- |
| Tasks | `GET`, `POST /tasks` | `GET`, `PATCH`, `DELETE /tasks/{task_id}` |
| Assessments | `GET`, `POST /assessments` | `GET`, `PATCH`, `DELETE /assessments/{assessment_id}` |
| Study sessions | `GET`, `POST /study-sessions` | `GET`, `PATCH`, `DELETE /study-sessions/{study_session_id}` |
| Resources | `GET`, `POST /resources` | `GET`, `PATCH`, `DELETE /resources/{resource_id}` |

Collection reads accept an optional `subject_id` query parameter. Create
requests take the record fields and a subject ID; the API assigns the signed-in
user ID. Each record is scoped to its owner, including reads, updates, deletes,
and subject references.

Run the Flet app from this directory with `python frontend/main.py`. It has
registration and login views, a subject template, and simple list/create
templates for each planner record, with complete and delete actions where they
apply. Set `MATRIC_PLANNER_API_URL` if the API is not running at
`http://localhost:8000`.
