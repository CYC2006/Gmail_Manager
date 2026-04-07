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

    email_list_view = ft.ListView(expand=True, spacing=4, padding=ft.padding.only(right=8))
    status_text = ft.Text("", color=ft.Colors.BLUE_200, size=13)

    def is_moodle(data) -> bool:
        """
        判斷是否為 Moodle 信件。
        gmail_reader.py 的 route_email() 用 sender.lower() 判斷 "moodle"，
        所以這裡也用同樣邏輯對 sender 判斷，而不是看 AI 回傳的 category。
        """
        return "moodle" in data['sender'].lower()

    # Map predefined AI categories and routing tags to Flet colors using a dictionary
    def get_tag_color(category: str):
        color_map = {
            # Moodle Categories
            "作業死線": ft.Colors.ORANGE_700,
            "作業公布": ft.Colors.BLUE_GREY_600,
            "繳交確認": ft.Colors.GREEN_700,
            "成績公布": ft.Colors.BLUE_700,
            "停課通知": ft.Colors.PURPLE_700,
            "考試相關": ft.Colors.RED_700,
            
            # General Email Categories
            "重要公告": ft.Colors.RED_700,
            "講座活動": ft.Colors.TEAL_700,
            "一般宣導": ft.Colors.BLUE_400,
            
            # Route Email Tags & Errors
            "合作社廣告": ft.Colors.BROWN_500,
            "外部學習": ft.Colors.INDIGO_500,
            "Analysis Failed": ft.Colors.RED_900
        }

        # Iterate through the dictionary keys to find a match in the category string
        for key, color in color_map.items():
            if key in category:
                return color
                
        return ft.Colors.GREY_600

    def create_email_card(data):
        # Determine color of card bg by unread or read
        card_bgcolor = "#444444" if data.get('is_unread') else "#2a2a2a"

        # TOP-LEFT：Moodle 用學士帽+文字，其他用寄件人名稱 ──
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

        return ft.Card(
            margin=ft.margin.symmetric(horizontal=10, vertical=3),
            content=ft.Container(
                bgcolor=card_bgcolor,
                # 右側 padding 縮小，讓按鈕不會離邊緣太遠
                padding=ft.padding.only(left=15, right=4, top=4, bottom=12),
                border_radius=10,
                content=ft.Column(
                    spacing=8,  # 兩排之間的間距
                    controls=[
                        # ── 上排：標題 ＋ 時間＋按鈕 ──
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=title_control,
                                    expand=True,
                                ),
                                ft.Row(
                                    controls=[
                                        ft.Text(
                                            data['time'],
                                            color=ft.Colors.OUTLINE,
                                            size=12,
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.MARK_EMAIL_READ,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            tooltip="標記已讀",
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.STAR_BORDER,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            icon_color=ft.Colors.YELLOW_600,
                                            tooltip="加星號",
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.ARCHIVE,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
                                            icon_color=ft.Colors.GREEN_400,
                                            tooltip="封存",
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE,
                                            icon_size=18,
                                            padding=ft.padding.all(2),
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
                        # ── 下排：分類 tag ＋ 摘要 ──
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Text(
                                        data['category'],
                                        size=11,
                                        color=ft.Colors.WHITE,
                                        weight=ft.FontWeight.BOLD,
                                        no_wrap=True,
                                    ),
                                    bgcolor=get_tag_color(data['category']),
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
                    ft.Text("Inbox", size=30, weight="bold"),
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