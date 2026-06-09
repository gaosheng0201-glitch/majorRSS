import os
import sys
import threading
import flet as ft

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import create_db_and_tables
from scheduler import start_scheduler

from ui.flet_views.dashboard import dashboard_view
from ui.flet_views.trackers import trackers_view
from ui.flet_views.settings import settings_view

def main(page: ft.Page):
    page.title = "MajorRSS Radar"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.window.min_width = 960
    page.window.min_height = 640

    create_db_and_tables()
    if os.environ.get("MAJORRSS_START_SCHEDULER") == "1":
        scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
        scheduler_thread.start()

    content_area = ft.Container(
        expand=True,
        padding=10,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=96,
        min_extended_width=180,
        group_alignment=-0.9,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.HOME, label="Dashboard"),
            ft.NavigationRailDestination(icon=ft.Icons.TRACK_CHANGES, label="Trackers"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS, label="Settings"),
        ],
        on_change=lambda e: on_nav_change(e.control.selected_index)
    )

    def on_nav_change(idx):
        if idx == 0:
            from ui.flet_views.dashboard import dashboard_view
            content_area.content = dashboard_view(page)
        elif idx == 1:
            from ui.flet_views.trackers import trackers_view
            content_area.content = trackers_view(page)
        elif idx == 2:
            from ui.flet_views.settings import settings_view
            content_area.content = settings_view(page)
        page.update()

    # Initial view
    on_nav_change(0)

    page.add(
        ft.Row(
            controls=[
                nav_rail,
                content_area
            ],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH
        )
    )
    page.update()

if __name__ == "__main__":
    ft.app(target=main)
