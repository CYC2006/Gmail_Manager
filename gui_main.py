import flet as ft
import os
import sys
import asyncio

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

    email_list_view = ft.ListView(expand=True, spacing=5)
    status_text = ft.Text("", color=ft.Colors.BLUE_200, size=13)

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
    # 3. Core Logic
    # ==========================

    async def fetch_task():
        nonlocal gmail_service
        try:
            if not gmail_service:
                # 同步函式用 to_thread 避免 block UI
                gmail_service = await asyncio.to_thread(get_gmail_service)

            email_list_view.controls.clear()
            page.update()

            # generator 的每一次 next() 都是 blocking（AI 分析），所以用 to_thread
            def get_next(gen):
                try:
                    return next(gen)
                except StopIteration:
                    return None

            gen = fetch_and_analyze_emails(gmail_service)
            while True:
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                email_list_view.controls.append(create_email_card(email_data))
                page.update()  # 每封完成立刻更新
                await asyncio.sleep(0)  # 讓出控制權給 event loop 渲染

            status_text.value = ""
            page.update()

        except Exception as ex:
            import traceback
            traceback.print_exc()
            status_text.value = f"載入失敗：{str(ex)}"
            page.update()

    def on_refresh_click(e):
        nonlocal gmail_service
        email_list_view.controls.clear()
        status_text.value = "載入中..."
        page.update()
        page.run_task(fetch_task)  # 用 run_task 啟動 async coroutine

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
                    status_text,
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        icon_color=ft.Colors.BLUE_200,
                        on_click=on_refresh_click
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=20, color="transparent"),
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

    on_refresh_click(None)

if __name__ == "__main__":
    ft.app(target=main)