import os

import flet as ft
import httpx


API_URL = os.getenv("MATRIC_PLANNER_API_URL", "http://localhost:8000")


async def main(page: ft.Page):
    page.title = "Matric Planner"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    def show_message(message: ft.Text, value: str) -> None:
        message.value = value
        page.update()

    async def show_subjects(login_data: dict) -> None:
        user = login_data["user"]
        token = login_data["access_token"]
        controls = [
            ft.Text(f"Welcome, {user.get('full_name') or user['username']}", size=24),
            ft.Text("Your subjects", size=18),
        ]

        for subject in login_data["subjects"]:
            if not subject["is_optional"]:
                controls.append(ft.Text(subject["name"], size=16))
                continue

            name_field = ft.TextField(label=subject["name"], value=subject["name"])
            message = ft.Text()

            async def save_optional_subject(
                _event,
                subject_id=subject["id"],
                field=name_field,
                feedback=message,
            ):
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        response = await client.patch(
                            f"{API_URL}/subjects/{subject_id}",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"name": field.value},
                        )
                    if response.is_success:
                        field.value = response.json()["name"]
                        field.label = field.value
                        show_message(feedback, "Saved")
                    else:
                        show_message(feedback, _error_message(response))
                except httpx.RequestError:
                    show_message(feedback, "Could not reach the planner API.")

            controls.extend(
                [
                    ft.Row(
                        [
                            name_field,
                            ft.Button(content="Save", on_click=save_optional_subject),
                        ]
                    ),
                    message,
                ]
            )

        async def log_out(_event):
            await show_login()

        controls.append(ft.Button(content="Log out", on_click=log_out))
        page.controls.clear()
        page.add(ft.Column(controls, spacing=12, width=500))
        page.update()

    async def log_in(identifier: str, password: str, message: ft.Text) -> None:
        if not identifier.strip() or not password:
            show_message(message, "Enter your username or email and password.")
            return

        login_field = "email" if "@" in identifier else "username"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{API_URL}/auth/login",
                    json={login_field: identifier.strip(), "password": password},
                )
            if response.is_success:
                await show_subjects(response.json())
            else:
                show_message(message, _error_message(response))
        except httpx.RequestError:
            show_message(message, "Could not reach the planner API.")

    async def show_login():
        identifier = ft.TextField(label="Username or email", autofocus=True)
        password = ft.TextField(label="Password", password=True)
        message = ft.Text()

        async def submit(_event):
            await log_in(identifier.value or "", password.value or "", message)

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
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        f"{API_URL}/auth/register",
                        json=registration,
                    )
                if response.status_code == 201:
                    await log_in(registration["username"], registration["password"], message)
                else:
                    show_message(message, _error_message(response))
            except httpx.RequestError:
                show_message(message, "Could not reach the planner API.")

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
