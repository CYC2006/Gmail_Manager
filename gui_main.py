import flet as ft
import os
import sys
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import get_gmail_service, fetch_and_analyze_emails, get_inbox_stats
from src.email_actions import mark_as_read, toggle_star, archive_email, trash_email

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

    email_list_view = ft.ListView(expand=True, spacing=4, padding=ft.padding.only(right=8))
    status_text = ft.Text("", color=ft.Colors.BLUE_200, size=13)

    stats_row = ft.Row(
        controls=[
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ALL_INBOX, size=13, color=ft.Colors.BLUE_GREY_300),
                    ft.Text("--", size=12, color=ft.Colors.BLUE_GREY_300, weight=ft.FontWeight.BOLD),
                ], spacing=3),
                bgcolor="#2a2a2a", border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                tooltip="Inbox 總數",
            ),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.MARK_EMAIL_UNREAD, size=13, color=ft.Colors.BLUE_300),
                    ft.Text("--", size=12, color=ft.Colors.BLUE_300, weight=ft.FontWeight.BOLD),
                ], spacing=3),
                bgcolor="#2a2a2a", border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                tooltip="未讀數",
            ),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.STAR, size=13, color=ft.Colors.YELLOW_600),
                    ft.Text("--", size=12, color=ft.Colors.YELLOW_600, weight=ft.FontWeight.BOLD),
                ], spacing=3),
                bgcolor="#2a2a2a", border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                tooltip="星號數",
            ),
        ],
        spacing=6,
    )

    inbox_text   = stats_row.controls[0].content.controls[1]
    unread_text  = stats_row.controls[1].content.controls[1]
    starred_text = stats_row.controls[2].content.controls[1]

    def is_moodle(data) -> bool:
        return "moodle" in data['sender'].lower()

    def get_tag_color(category: str):
        color_map = {
            "作業死線": ft.Colors.ORANGE_700,
            "作業公布": ft.Colors.BLUE_GREY_600,
            "繳交確認": ft.Colors.GREEN_700,
            "成績公布": ft.Colors.BLUE_700,
            "停課通知": ft.Colors.PURPLE_700,
            "考試相關": ft.Colors.RED_700,
            "重要公告": ft.Colors.RED_700,
            "講座活動": ft.Colors.TEAL_700,
            "一般宣導": ft.Colors.BLUE_400,
            "其他廣告": ft.Colors.BROWN_500,
            "外部學習": ft.Colors.INDIGO_500,
            "Analysis Failed": ft.Colors.RED_900,
        }
        for key, color in color_map.items():
            if key in category:
                return color
        return ft.Colors.GREY_600

    def create_email_card(data):
        card_bgcolor = "#444444" if data.get('is_unread') else "#2a2a2a"
        email_id = data['id']

        is_starred_state = [data.get('is_starred', False)]

        # [CHANGE 3] 四個按鈕的 handler，操作後同步 Gmail 並更新 UI
        async def on_mark_read(e):
            e.control.parent.parent.parent.parent.bgcolor = "#2a2a2a"
            page.update()

            await asyncio.to_thread(mark_as_read, gmail_service, email_id)

        async def on_star(e, card_ref):
            is_starred_state[0] = not is_starred_state[0]
            e.control.icon = ft.Icons.STAR if is_starred_state[0] else ft.Icons.STAR_BORDER
            e.control.icon_color = ft.Colors.YELLOW_400 if is_starred_state[0] else ft.Colors.YELLOW_600
            page.update()

            await asyncio.to_thread(toggle_star, gmail_service, email_id, is_starred_state[0])

        async def on_archive(e, card_ref):
            email_list_view.controls.remove(card_ref) # remove from INBOX
            page.update()

            await asyncio.to_thread(archive_email, gmail_service, email_id)

        async def on_trash(e, card_ref):
            email_list_view.controls.remove(card_ref) # remove from INBOX
            page.update()

            await asyncio.to_thread(trash_email, gmail_service, email_id)

        if is_moodle(data):
            title_control = ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SCHOOL, size=20, color=ft.Colors.ORANGE_300),
                    ft.Text(
                        " Moodle",
                        weight=ft.FontWeight.BOLD,
                        size=18,
                        color=ft.Colors.ORANGE_300,
                    ),
                ],
                spacing=4,
            )
        else:
            title_control = ft.Text(
                data['sender'],
                weight=ft.FontWeight.BOLD,
                size=18,
                color=ft.Colors.WHITE,
                overflow=ft.TextOverflow.ELLIPSIS,
                max_lines=1,
            )

        card = ft.Card(
            margin=ft.margin.symmetric(horizontal=10, vertical=3),
            content=ft.Container(
                bgcolor=card_bgcolor,
                padding=ft.padding.only(left=15, right=4, top=4, bottom=12),
                border_radius=10,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Container(content=title_control, expand=True),
                                ft.Row(
                                    controls=[
                                        ft.Text(data['time'], color=ft.Colors.OUTLINE, size=12),
                                        ft.IconButton(
                                            icon=ft.Icons.MARK_EMAIL_READ,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            tooltip="標記已讀",
                                            on_click=lambda e: page.run_task(on_mark_read, e),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.STAR if is_starred_state[0] else ft.Icons.STAR_BORDER,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            icon_color=ft.Colors.YELLOW_600,
                                            tooltip="加星號",
                                            on_click=lambda e: page.run_task(on_star, e, card),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.ARCHIVE,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            icon_color=ft.Colors.GREEN_400,
                                            tooltip="封存",
                                            on_click=lambda e: page.run_task(on_archive, e, card),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            icon_color=ft.Colors.RED_400,
                                            tooltip="刪除",
                                            on_click=lambda e: page.run_task(on_trash, e, card),
                                        ),
                                    ],
                                    spacing=0,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Text(data['category'], size=13, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, no_wrap=True),
                                    bgcolor=get_tag_color(data['category']),
                                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                    border_radius=5,
                                ),
                                ft.Text(data['summary'], size=13, expand=True, color="#bbbbbb", overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                ),
            ),
        )
        return card

    # ==========================
    # 3. Core Logic
    # ==========================

    async def fetch_task():
        nonlocal gmail_service
        try:
            if not gmail_service:
                gmail_service = await asyncio.to_thread(get_gmail_service)

            stats = await asyncio.to_thread(get_inbox_stats, gmail_service)
            inbox_text.value   = str(stats["inbox"])
            unread_text.value  = str(stats["unread"])
            starred_text.value = str(stats["starred"])
            page.update()

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
        status_text.value = "Loading..."
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
            ft.ListTile(leading=ft.Icon(ft.Icons.INBOX), title=ft.Text("Inbox"), selected=True),
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
                    ft.Row([
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.INBOX, size=28, color=ft.Colors.WHITE),
                                ft.Text("Inbox", size=30, weight="bold"),
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.only(left=10, right=10),
                        ),
                        stats_row,
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Row([
                        status_text,
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_color=ft.Colors.BLUE_200,
                            on_click=on_refresh_click,
                        ),
                    ], spacing=0),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
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