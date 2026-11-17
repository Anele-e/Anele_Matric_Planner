import os

import flet as ft
import httpx


API_URL = os.getenv("MATRIC_PLANNER_API_URL", "http://localhost:8000").rstrip("/")
ENTITY_TEMPLATES = {
    "Tasks": {
        "path": "/tasks",
        "fields": [
            ("title", "Task title", "text", True),
            ("subject_id", "Subject ID", "int", True),
            ("description", "Description", "text", False),
            ("due_date", "Due date", "text", False),
            ("priority", "Priority (1-5)", "int", False),
        ],
    },
    "Assessments": {
        "path": "/assessments",
        "fields": [
            ("title", "Assessment title", "text", True),
            ("subject_id", "Subject ID", "int", True),
            ("assessment_type", "Type", "text", False),
            ("assessment_date", "Assessment date", "text", False),
            ("total_marks", "Total marks", "float", False),
            ("description", "Description", "text", False),
        ],
    },
    "Study sessions": {
        "path": "/study-sessions",
        "fields": [
            ("subject_id", "Subject ID", "int", True),
            ("start_time", "Start time", "text", True),
            ("end_time", "End time", "text", False),
            ("topic", "Topic", "text", False),
            ("notes", "Notes", "text", False),
        ],
    },
    "Resources": {
        "path": "/resources",
        "fields": [
            ("title", "Resource title", "text", True),
            ("url", "URL", "text", True),
            ("subject_id", "Subject ID", "int", True),
            ("resource_type", "Type", "text", False),
            ("description", "Description", "text", False),
        ],
    },
}


async def main(page: ft.Page):
    page.title = "Matric Planner"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    session = {"token": None, "user": None, "subjects": []}

    async def api_request(method: str, path: str, body: dict | None = None):
        try:
            headers = {}
            if session["token"]:
                headers["Authorization"] = f"Bearer {session['token']}"
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.request(
                    method,
                    f"{API_URL}{path}",
                    headers=headers,
                    json=body,
                )
            if response.is_success:
                return (response.json() if response.content else None), None
            return None, _error_message(response)
        except httpx.RequestError:
            return None, "Could not reach the planner API."

    def show_message(message: ft.Text, value: str) -> None:
        message.value = value
        page.update()

    async def show_login():
        identifier = ft.TextField(label="Username or email", autofocus=True)
        password = ft.TextField(label="Password", password=True)
        message = ft.Text()

        async def submit(_event):
            login_field = "email" if "@" in (identifier.value or "") else "username"
            data, error = await api_request(
                "POST",
                "/auth/login",
                {login_field: (identifier.value or "").strip(), "password": password.value or ""},
            )
            if error:
                show_message(message, error)
                return
            session["token"] = data["access_token"]
            session["user"] = data["user"]
            session["subjects"] = data["subjects"]
            await show_dashboard()

        async def open_register(_event):
            await show_register()

        page.controls.clear()
        page.add(
            ft.Column(
                [
                    ft.Text("Matric Planner", size=28),
                    identifier,
                    password,
                    ft.Button(content="Log in", on_click=submit),
                    ft.Button(content="Create account", on_click=open_register),
                    message,
                ],
                spacing=12,
                width=400,
            )
        )
        page.update()

    async def show_register():
        username = ft.TextField(label="Username")
        email = ft.TextField(label="Email")
        full_name = ft.TextField(label="Full name")
        grade = ft.TextField(label="Grade", value="12")
        password = ft.TextField(label="Password (at least 8 characters)", password=True)
        message = ft.Text()

        async def submit(_event):
            try:
                grade_value = int(grade.value or "")
            except ValueError:
                show_message(message, "Enter your grade as a number.")
                return

            registration = {
                "username": username.value or "",
                "email": email.value or "",
                "full_name": full_name.value or None,
                "grade": grade_value,
                "password": password.value or "",
            }
            _, error = await api_request("POST", "/auth/register", registration)
            if error:
                show_message(message, error)
                return
            data, error = await api_request(
                "POST",
                "/auth/login",
                {"username": registration["username"], "password": registration["password"]},
            )
            if error:
                show_message(message, error)
                return
            session["token"] = data["access_token"]
            session["user"] = data["user"]
            session["subjects"] = data["subjects"]
            await show_dashboard()

        async def back_to_login(_event):
            await show_login()

        page.controls.clear()
        page.add(
            ft.Column(
                [
                    ft.Text("Create account", size=28),
                    username,
                    email,
                    full_name,
                    grade,
                    password,
                    ft.Button(content="Register", on_click=submit),
                    ft.Button(content="Back to log in", on_click=back_to_login),
                    message,
                ],
                spacing=12,
                width=400,
            )
        )
        page.update()

    def navigation():
        async def open_subjects(_event):
            await show_subjects()

        buttons = [ft.Button(content="Subjects", on_click=open_subjects)]
        for name in ENTITY_TEMPLATES:
            async def open_entity(_event, entity_name=name):
                await show_entity(entity_name)

            buttons.append(ft.Button(content=name, on_click=open_entity))
        return ft.Row(buttons, wrap=True, spacing=8)

    async def show_dashboard():
        user = session["user"]

        async def log_out(_event):
            session["token"] = None
            session["user"] = None
            session["subjects"] = []
            await show_login()

        controls = [
            ft.Text(f"Welcome, {user.get('full_name') or user['username']}", size=24),
            ft.Text("Choose a planner template:", size=16),
            navigation(),
            ft.Button(content="Log out", on_click=log_out),
        ]
        page.controls.clear()
        page.add(ft.Column(controls, spacing=12, width=700, scroll=ft.ScrollMode.AUTO))
        page.update()

    async def show_subjects():
        subjects, error = await api_request("GET", "/subjects")
        if error:
            subjects = session["subjects"]
        else:
            session["subjects"] = subjects
        controls = [
            ft.Text("Your subjects", size=24),
            navigation(),
        ]
        for subject in subjects:
            if not subject["is_optional"]:
                controls.append(ft.Text(f"{subject['name']} (ID: {subject['id']})", size=16))
                continue

            field = ft.TextField(label=subject["name"], value=subject["name"])
            feedback = ft.Text()

            async def save_optional_subject(
                _event,
                subject_id=subject["id"],
                name_field=field,
                message=feedback,
            ):
                updated, error = await api_request(
                    "PATCH",
                    f"/subjects/{subject_id}",
                    {"name": name_field.value or ""},
                )
                if not error:
                    name_field.label = updated["name"]
                show_message(message, error or "Saved")

            controls.extend(
                [
                    ft.Text(f"Subject ID: {subject['id']}"),
                    ft.Row(
                        [field, ft.Button(content="Save", on_click=save_optional_subject)],
                        wrap=True,
                    ),
                    feedback,
                ]
            )

        async def back(_event):
            await show_dashboard()

        controls.append(ft.Button(content="Home", on_click=back))
        page.controls.clear()
        page.add(ft.Column(controls, spacing=12, width=700, scroll=ft.ScrollMode.AUTO))
        page.update()

    async def show_entity(name: str):
        template = ENTITY_TEMPLATES[name]
        message = ft.Text()
        fields = {}
        form = [ft.Text(name, size=24), navigation()]

        for key, label, _kind, _required in template["fields"]:
            default = str(session["subjects"][0]["id"]) if key == "subject_id" and session["subjects"] else ""
            field = ft.TextField(label=label, value=default)
            fields[key] = field
            form.append(field)

        async def refresh_records():
            records, error = await api_request("GET", template["path"])
            if error:
                show_message(message, error)
                return []
            return records

        async def refresh_view():
            records = await refresh_records()
            rows = []
            for record in records:
                title = record.get("title") or record.get("topic") or "Study session"
                detail_parts = [f"#{record['id']}", title]
                for detail_key in ("due_date", "assessment_date", "start_time", "url"):
                    if record.get(detail_key):
                        detail_parts.append(f"{detail_key.replace('_', ' ')}: {record[detail_key]}")
                if record.get("completed"):
                    detail_parts.append("Completed")

                actions = []
                if "completed" in record and not record["completed"]:
                    async def mark_complete(_event, record_id=record["id"]):
                        _, error = await api_request(
                            "PATCH", f"{template['path']}/{record_id}", {"completed": True}
                        )
                        show_message(message, error or "Updated")
                        await refresh_view()

                    actions.append(ft.Button(content="Complete", on_click=mark_complete))

                async def delete_record(_event, record_id=record["id"]):
                    _, error = await api_request("DELETE", f"{template['path']}/{record_id}")
                    show_message(message, error or "Deleted")
                    await refresh_view()

                actions.append(ft.Button(content="Delete", on_click=delete_record))
                rows.append(
                    ft.Column(
                        [ft.Text(" · ".join(detail_parts)), ft.Row(actions, wrap=True)],
                        spacing=4,
                    )
                )

            if not records:
                rows.append(ft.Text("No records yet."))
            record_list.controls = rows
            page.update()

        async def create_record(_event):
            payload = {}
            try:
                for key, _label, kind, required in template["fields"]:
                    value = (fields[key].value or "").strip()
                    if not value:
                        if required:
                            show_message(message, f"{key.replace('_', ' ').capitalize()} is required.")
                            return
                        continue
                    if kind == "int":
                        payload[key] = int(value)
                    elif kind == "float":
                        payload[key] = float(value)
                    else:
                        payload[key] = value
            except ValueError:
                show_message(message, "Check the numeric values and try again.")
                return

            _, error = await api_request("POST", template["path"], payload)
            show_message(message, error or "Saved")
            if not error:
                for field in fields.values():
                    if field.label != "Subject ID":
                        field.value = ""
                await refresh_view()

        form.extend(
            [
                ft.Button(content=f"Add {name[:-1] if name.endswith('s') else name}", on_click=create_record),
                message,
                ft.Text("Saved records", size=18),
            ]
        )
        record_list = ft.Column(spacing=10)
        form.append(record_list)

        async def back(_event):
            await show_dashboard()

        form.append(ft.Button(content="Home", on_click=back))
        page.controls.clear()
        page.add(ft.Column(form, spacing=10, width=700, scroll=ft.ScrollMode.AUTO))
        page.update()
        await refresh_view()

    await show_login()


def _error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", "Request failed.")
    except ValueError:
        return f"Request failed ({response.status_code})."

    if isinstance(detail, list):
        return "; ".join(item.get("msg", "Invalid input") for item in detail)
    return str(detail)


if __name__ == "__main__":
    ft.run(main)
