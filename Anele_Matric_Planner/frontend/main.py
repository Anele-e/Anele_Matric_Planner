import flet as ft
import httpx

API_URL = "http://localhost:8000"

async def main(page: ft.Page):
    page.title = "Matric Planner Application"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    # Create a TextField for user input
    input_field = ft.TextField(label="Enter your name", autofocus=True)

    # Create a Text control to display the API response
    response_text = ft.Text(value="", size=20)

    # Define a function to handle button click
    async def on_button_click(e):
        user_input = input_field.value
        if user_input:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{API_URL}/?name={user_input}")
                    if response.status_code == 200:
                        data = response.json()
                        response_text.value = f"API Response: {data['message']}"
                    else:
                        response_text.value = f"Error: {response.status_code}"
            except Exception as ex:
                response_text.value = f"Request failed: {ex}"
        else:
            response_text.value = "Please enter your name."

        # Update the page to reflect changes
        page.update()

    # Create a Button to trigger the API call
    submit_button = ft.Button(content="Submit", on_click=on_button_click)

    # Add controls to the page
    page.add(input_field, submit_button, response_text)

if __name__ == "__main__":
    ft.run(main)
