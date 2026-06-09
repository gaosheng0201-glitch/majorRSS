import flet as ft
from db.database import get_session
from db.models import IntelReport, TrendAlert, PipelineStatus, RawArticle
from sqlmodel import select, func

def dashboard_view(page: ft.Page) -> ft.Control:
    session = get_session()
    
    # Header
    header = ft.Row(
        [
            ft.Text("Dashboard", size=32, weight="bold"),
            ft.Container(expand=True),
            ft.ElevatedButton(
                content=ft.Row([ft.Icon("refresh"), ft.Text("Refresh")]),
                on_click=lambda e: (page.views.clear(), page.go("/dashboard") if hasattr(page, "go") else None)
            )
        ]
    )

    print("DEBUG: Start dashboard_view", flush=True)
    content_col = ft.Column(scroll="auto", spacing=20)
    
    # Pending AI Metric
    print("DEBUG: Querying pending count", flush=True)
    pending_count = session.exec(select(func.count()).where(RawArticle.processed == False)).one()
    print("DEBUG: Pending count queried", flush=True)
    metric_card = ft.Card(
        content=ft.Container(
            padding=20,
            content=ft.Column([
                ft.Text("Pending AI Processing", size=16),
                ft.Text(str(pending_count), size=36, weight="bold")
            ])
        )
    )
    content_col.controls.append(header)
    content_col.controls.append(metric_card)

    # Recent Alerts
    alerts = session.exec(select(TrendAlert).order_by(TrendAlert.created_at.desc()).limit(3)).all()
    if alerts:
        alerts_col = ft.Column(spacing=10)
        for alert in alerts:
            alerts_col.controls.append(
                ft.Container(
                    bgcolor="red",
                    padding=15,
                    border_radius=10,
                    content=ft.Column([
                        ft.Text(f"⚠️ Trend Alert: {alert.entity_name}", weight="bold", color="white"),
                        ft.Text(alert.alert_summary, color="white")
                    ])
                )
            )
        content_col.controls.append(alerts_col)

    # Intel Reports
    reports_text = ft.Text("Latest Intelligence", size=24, weight="bold")
    content_col.controls.append(reports_text)
    
    reports = session.exec(
        select(IntelReport)
        .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .order_by(IntelReport.event_timestamp.desc(), IntelReport.created_at.desc())
        .limit(20)
    ).all()

    if not reports:
        content_col.controls.append(ft.Text("No recent intelligence found."))
    else:
        for r in reports:
            raw = session.get(RawArticle, r.raw_article_id)
            title = raw.title if raw else "Untitled"
            
            card = ft.Card(
                elevation=2,
                content=ft.Container(
                    padding=20,
                    content=ft.Column([
                        ft.Text(title, size=18, weight="bold"),
                        ft.Text(f"⭐ {r.importance_score}★ | Section: {r.radar_section}"),
                        ft.Markdown(
                            r.llm_summary,
                            selectable=True,
                            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED
                        ),
                    ], spacing=10)
                )
            )
            content_col.controls.append(card)

    print("DEBUG: End dashboard_view", flush=True)
    return ft.Container(
        content=content_col,
        expand=True,
        padding=10
    )
