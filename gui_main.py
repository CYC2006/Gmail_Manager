import flet as ft
import os
import sys
import threading

# Ensure absolute import path from src directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import get_gmail_service, fetch_and_analyze_emails

def main(page: ft.Page):
    # ==========================
    # 1. Window Base Settings
    # ==========================
    page.title = "NCKU Gmail Manager"
    page.window.width = 1100
    page.window.height = 700
    page.window.resizable = False 
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    gmail_service = None

    # ==========================
    # 2. UI Components
    # ==========================
    
    # The ListView is permanently bound to the layout, perfectly safe.
    email_list_view = ft.ListView(expand=True, spacing=5)

    # The loading indicator is now a fixed-height Row, avoiding any flex layout crashes.
    loading_indicator = ft.Row(
        controls=[
            ft.ProgressRing(width=24, height=24, stroke_width=3, color=ft.Colors.BLUE_200),
            ft.Text("AI is analyzing your NCKU emails, please wait...", color=ft.Colors.BLUE_200, size=16)
        ],
        alignment=ft.MainAxisAlignment.CENTER,
        visible=False
    )

    def create_email_card(data):
        return ft.Card(
            margin=10, 
            content=ft.Container(
                bgcolor="#2d2d2d", 
                padding=15,
                border_radius=12,
                content=ft.Column([
                    ft.Row([
                        ft.Text(data['sender'], weight=ft.FontWeight.BOLD, size=16, expand=True),
                        ft.Text(data['time'], color=ft.Colors.OUTLINE, size=12)
                    ]),
                    ft.Row([
                        ft.Container(
                            content=ft.Text(data['category'], size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                            bgcolor=data['tag_color'],
                            padding=5, 
                            border_radius=5,
                        ),
                        ft.Text(data['summary'], size=14, expand=True, color="#cccccc")
                    ]),
                    ft.Row([
                        ft.IconButton(icon=ft.Icons.MARK_EMAIL_READ, icon_size=18),
                        ft.IconButton(icon=ft.Icons.STAR_BORDER, icon_size=18, icon_color=ft.Colors.YELLOW_600),
                        ft.IconButton(icon=ft.Icons.ARCHIVE, icon_size=18, icon_color=ft.Colors.GREEN_400),
                        ft.IconButton(icon=ft.Icons.DELETE, icon_size=18, icon_color=ft.Colors.RED_400),
                    ], alignment=ft.MainAxisAlignment.END, spacing=0)
                ])
            )
        )

    # ==========================
    # 3. Core Logic (State Updates)
    # ==========================

    def on_refresh_click(e):
        nonlocal gmail_service
        
        # State: Loading
        email_list_view.controls.clear()
        loading_indicator.visible = True
        page.update()

        def fetch_task():
            nonlocal gmail_service
            try:
                if not gmail_service:
                    gmail_service = get_gmail_service()
                
                real_emails = fetch_and_analyze_emails(gmail_service)
                
                # State: Finished fetching
                email_list_view.controls.clear()
                loading_indicator.visible = False

                for email_data in real_emails:
                    email_list_view.controls.append(create_email_card(email_data))
                
                page.update()
                print("[GUI] Refresh completed successfully.")
                
            except Exception as ex:
                import traceback
                traceback.print_exc()
                loading_indicator.visible = False
                email_list_view.controls.append(
                    ft.Text(f"Failed to load emails: {str(ex)}", color=ft.Colors.RED_400)
                )
                page.update()

        # Dispatch background thread
        threading.Thread(target=fetch_task, daemon=True).start()

    # ==========================
    # 4. Layout Assembly
    # ==========================
    
    sidebar = ft.Container(
        width=250, bgcolor="#1e1e1e", padding=20,
        content=ft.Column([
            ft.Text("NCKU Gmail Manager", size=18, weight="bold", color=ft.Colors.BLUE_200),
            ft.Divider(height=20),
            ft.ListTile(leading=ft.Icon(ft.Icons.INBOX), title=ft.Text("Unread"), selected=True),
            ft.ListTile(leading=ft.Icon(ft.Icons.SCHOOL), title=ft.Text("Moodle")),
            ft.ListTile(leading=ft.Icon(ft.Icons.CAMPAIGN), title=ft.Text("Announcements")),
            ft.Divider(height=20),
            ft.ListTile(leading=ft.Icon(ft.Icons.SEND), title=ft.Text("Sent")),
            ft.ListTile(leading=ft.Icon(ft.Icons.ALL_INBOX), title=ft.Text("All Mails")),
            ft.ListTile(leading=ft.Icon(ft.Icons.DELETE), title=ft.Text("Trash")),
        ])
    )

    main_content = ft.Container(
        expand=True, padding=30, bgcolor="#121212",
        content=ft.Column(
            expand=True,
            controls=[
                ft.Row([
                    ft.Text("Inbox", size=28, weight="bold"),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH, 
                        icon_color=ft.Colors.BLUE_200, 
                        on_click=on_refresh_click 
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=20, color="transparent"),
                
                # The ultimate safe layout: Side-by-side in the controls array.
                loading_indicator,
                email_list_view 
            ]
        )
    )

    page.add(
        ft.Row(
            expand=True, 
            spacing=0, 
            vertical_alignment=ft.CrossAxisAlignment.STRETCH, 
            controls=[
                sidebar, 
                ft.VerticalDivider(width=1, color=ft.Colors.OUTLINE_VARIANT), 
                main_content
            ]
        )
    )
    
    # Start loading automatically when the app launches
    on_refresh_click(None)

if __name__ == "__main__":
    ft.run(main)