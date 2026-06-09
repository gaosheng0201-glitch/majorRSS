import flet as ft
import json
from db.database import get_session
from db.models import Tracker
from sqlmodel import select

def trackers_view(page: ft.Page) -> ft.Control:
    session = get_session()
    
    def load_trackers():
        return session.exec(select(Tracker)).all()

    def format_target(value: str) -> str:
        try:
            data = json.loads(value)
            parts = []
            if data.get("urls"):
                parts.append(f"{len(data['urls'])} URLs")
            if data.get("keywords"):
                parts.append(f"{len(data['keywords'])} KWs")
            if data.get("accounts"):
                parts.append(f"{len(data['accounts'])} Accs")
            return ", ".join(parts) if parts else "Empty"
        except Exception:
            return value if len(value) <= 48 else f"{value[:45]}..."
        
    trackers = load_trackers()
    
    def open_add_dialog(e):
        name_input = ft.TextField(label="Tracker Name", autofocus=True)
        section_input = ft.TextField(label="Radar Section", value="Technology")
        tracker_type_input = ft.Dropdown(
            label="Tracker Type",
            value="URL",
            options=[
                ft.dropdown.Option("URL"),
                ft.dropdown.Option("KEYWORD"),
                ft.dropdown.Option("ACCOUNT"),
            ]
        )
        interval_input = ft.TextField(label="Fetch Interval (m)", value="360", keyboard_type="number")
        target_input = ft.TextField(label="Target URL / Keyword / Account")
        
        def save_tracker(e):
            try:
                interval = int(interval_input.value or 360)
            except ValueError:
                interval = 360

            new_t = Tracker(
                name=name_input.value or "Unnamed",
                tracker_type=tracker_type_input.value or "URL",
                target=target_input.value or "",
                radar_section=section_input.value or "Technology",
                fetch_interval_minutes=interval,
            )
            session.add(new_t)
            session.commit()
            page.close(dialog)
            page.snack_bar = ft.SnackBar(ft.Text("Tracker added. Reopen Trackers to refresh the table."))
            page.open(page.snack_bar)
            page.update()
            
        dialog = ft.AlertDialog(
            title=ft.Text("Add New Tracker"),
            content=ft.Column(
                [name_input, target_input, tracker_type_input, section_input, interval_input],
                tight=True,
                width=420,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: page.close(dialog)),
                ft.ElevatedButton(content=ft.Text("Save"), on_click=save_tracker)
            ]
        )
        page.open(dialog)

    header = ft.Row([
        ft.Text("Trackers Management", size=32, weight="bold"),
        ft.Container(expand=True),
        ft.ElevatedButton(content=ft.Row([ft.Icon("add"), ft.Text("Add Tracker")]), on_click=open_add_dialog)
    ])
    
    columns = [
        ft.DataColumn(ft.Text("ID")),
        ft.DataColumn(ft.Text("Name")),
        ft.DataColumn(ft.Text("Type")),
        ft.DataColumn(ft.Text("Target")),
        ft.DataColumn(ft.Text("Section")),
        ft.DataColumn(ft.Text("Interval(m)")),
        ft.DataColumn(ft.Text("Status")),
        ft.DataColumn(ft.Text("Actions")),
    ]
    
    rows = []
    for t in trackers:
        status_icon = ft.Icon("check_circle", color="green") if t.is_active else ft.Icon("cancel", color="red")
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(t.id))),
                    ft.DataCell(ft.Text(t.name)),
                    ft.DataCell(ft.Text(t.tracker_type)),
                    ft.DataCell(ft.Text(format_target(t.target))),
                    ft.DataCell(ft.Text(t.radar_section)),
                    ft.DataCell(ft.Text(str(t.fetch_interval_minutes))),
                    ft.DataCell(status_icon),
                    ft.DataCell(ft.IconButton(icon="delete", icon_color="error", tooltip="Delete Tracker"))
                ]
            )
        )
        
    table = ft.DataTable(
        columns=columns,
        rows=rows,
    )
    
    return ft.Container(
        content=ft.Column(
            controls=[
                header,
                ft.Column(
                    controls=[
                        ft.Row(
                            controls=[table],
                            scroll=ft.ScrollMode.AUTO,
                        )
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            ],
            expand=True,
        ),
        expand=True,
        padding=20
    )
