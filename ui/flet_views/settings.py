import flet as ft

def settings_view(page: ft.Page) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("Settings & Auth (WIP)", size=30, weight=ft.FontWeight.BOLD),
        ],
        expand=True,
    )
