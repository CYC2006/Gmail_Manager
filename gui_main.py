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

    email_list_view = ft.ListView(expand=True, spacing=4)
    status_text = ft.Text("", color=ft.Colors.BLUE_200, size=13)

    def get_sub_category_color(category):
        """為 Moodle 子分類決定 tag 顏色"""
        if "作業死線" in category or "Deadline" in category:
            return ft.Colors.ORANGE_600
        elif "繳交確認" in category or "繳交" in category:
            return ft.Colors.GREEN_600
        elif "考試" in category:
            return ft.Colors.RED_600
        elif "停課" in category:
            return ft.Colors.PURPLE_600
        elif "成績" in category:
            return ft.Colors.BLUE_600
        else:
            return ft.Colors.GREY_600

    def create_email_card(data):
        is_moodle = "Moodle" in data['category'] or "📚" in data['category']

        if is_moodle:
            # Moodle 專屬標題：學士帽 icon + "Moodle"
            sender_widget = ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SCHOOL, size=16, color=ft.Colors.ORANGE_300),
                    ft.Text("Moodle", weight=ft.FontWeight.BOLD, size=15, color=ft.Colors.ORANGE_300),
                ],
                spacing=5,
            )
            tag_color = get_sub_category_color(data['category'])
        else:
            sender_widget = ft.Text(
                data['sender'],
                weight=ft.FontWeight.BOLD,
                size=15,
                expand=True,
                color=ft.Colors.WHITE,
            )
            tag_color = data['tag_color']

        return ft.Card(
            margin=ft.margin.symmetric(horizontal=10, vertical=3),
            content=ft.Container(
                bgcolor="#2a2a2a",
                padding=ft.padding.symmetric(horizontal=15, vertical=10),
                border_radius=10,
                content=ft.Column(
                    spacing=6,
                    controls=[
                        # 上排：寄件人/Moodle icon ＋ 右側時間＋按鈕
                        ft.Row(
                            controls=[
                                # 左側寄件人
                                ft.Container(content=sender_widget, expand=True),
                                # 右側：時間 + 四個按鈕
                                ft.Row(
                                    controls=[
                                        ft.Text(data['time'], color=ft.Colors.OUTLINE, size=11),
                                        ft.IconButton(
                                            icon=ft.Icons.MARK_EMAIL_READ,
                                            icon_size=16,
                                            padding=0,
                                            tooltip="標記已讀",
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.STAR_BORDER,
                                            icon_size=16,
                                            padding=0,
                                            icon_color=ft.Colors.YELLOW_600,
                                            tooltip="加星號",
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.ARCHIVE,
                                            icon_size=16,
                                            padding=0,
                                            icon_color=ft.Colors.GREEN_400,
                                            tooltip="封存",
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE,
                                            icon_size=16,
                                            padding=0,
                                            icon_color=ft.Colors.RED_400,
                                            tooltip="刪除",
                                        ),
                                    ],
                                    spacing=0,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        # 下排：分類 tag + 摘要
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Text(
                                        data['category'],
                                        size=11,
                                        color=ft.Colors.WHITE,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    bgcolor=tag_color,
                                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                    border_radius=5,
                                ),
                                ft.Text(
                                    data['summary'],
                                    size=13,
                                    expand=True,
                                    color="#bbbbbb",
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    max_lines=1,
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                ),
            ),
        )

    # ==========================
    # 3. Core Logic
    # ==========================

    async def fetch_task():
        nonlocal gmail_service
        try:
            if not gmail_service:
                gmail_service = await asyncio.to_thread(get_gmail_service)

            email_list_view.controls.clear()
            page.update()

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
                page.update()
                await asyncio.sleep(0)

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
        page.run_task(fetch_task)

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
                        on_click=on_refresh_click,
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=20, color="transparent"),
                email_list_view,
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
                main_content,
            ]
        )
    )

    on_refresh_click(None)

if __name__ == "__main__":
    ft.app(target=main)