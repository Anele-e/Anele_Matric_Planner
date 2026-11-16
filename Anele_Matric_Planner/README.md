# Matric Planner API

The backend is a FastAPI application. It stores registered users in SQLite at
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
password:

```json
{
  "email": "anele@example.com",
  "password": "a-long-password"
}
```

A successful login returns a 30-minute bearer access token and the public
profile. Invalid credentials return `401 Unauthorized`.
