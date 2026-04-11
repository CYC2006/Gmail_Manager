import flet as ft
import os
import sys
import ssl
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import get_gmail_service, fetch_and_analyze_emails, get_inbox_stats
from src.email_actions import mark_as_read, toggle_star, archive_email, trash_email
from src.db_manager import delete_analysis

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

    svc = {"service": None}   # mutable holder so all closures can rebuild the service on SSL error
    all_emails = []
    shown_email_ids = {}      # {email_id: _index} — tracks rendered emails and their inbox position
    current_view = ["inbox"]  # mutable container for nonlocal-like access
    fetch_gen = [0]           # increments on every refresh to cancel stale background tasks
    ui_lock = asyncio.Lock()  # prevents background fetch and user actions from modifying the list simultaneously

    PAGE_SIZE = 50
    MAX_PAGES = 5             # max pages fetched in background (1 page = 50 emails)

    # ==========================
    # 2. UI Components
    # ==========================

    email_list_view = ft.ListView(expand=True, spacing=4, padding=ft.padding.only(right=8))
    status_text = ft.Text("", color=ft.Colors.BLUE_200, size=13)

    user_email_text = ft.Text("Loading...", size=12, color=ft.Colors.OUTLINE)

    stats_row = ft.Row(
        controls=[
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ALL_INBOX, size=13, color=ft.Colors.BLUE_GREY_300),
                    ft.Text("--", size=12, color=ft.Colors.BLUE_GREY_300, weight=ft.FontWeight.BOLD),
                ], spacing=3),
                bgcolor="#2a2a2a", border_radius=6,
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                tooltip="Inbox 總數",
            ),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.MARK_EMAIL_UNREAD, size=13, color=ft.Colors.BLUE_300),
                    ft.Text("--", size=12, color=ft.Colors.BLUE_300, weight=ft.FontWeight.BOLD),
                ], spacing=3),
                bgcolor="#2a2a2a", border_radius=6,
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                tooltip="未讀數",
            ),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.STAR, size=13, color=ft.Colors.YELLOW_600),
                    ft.Text("--", size=12, color=ft.Colors.YELLOW_600, weight=ft.FontWeight.BOLD),
                ], spacing=3),
                bgcolor="#2a2a2a", border_radius=6,
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
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

        async def _call_with_ssl_retry(fn, *args):
            """Call a Gmail API function, rebuilding the service once on SSL error."""
            try:
                await asyncio.to_thread(fn, svc["service"], *args)
            except (ssl.SSLError, OSError) as ex:
                if "SSL" not in str(ex) and not isinstance(ex, ssl.SSLError):
                    raise
                print(f"[SSL] Connection stale, rebuilding service and retrying... ({ex})")
                svc["service"] = await asyncio.to_thread(get_gmail_service)
                await asyncio.to_thread(fn, svc["service"], *args)

        async def on_mark_read(e):
            e.control.parent.parent.parent.parent.bgcolor = "#2a2a2a"
            page.update()
            await _call_with_ssl_retry(mark_as_read, email_id)

        async def on_star(e, card_ref):
            is_starred_state[0] = not is_starred_state[0]
            e.control.icon = ft.Icons.STAR if is_starred_state[0] else ft.Icons.STAR_BORDER
            e.control.icon_color = ft.Colors.YELLOW_400 if is_starred_state[0] else ft.Colors.YELLOW_600
            page.update()
            await _call_with_ssl_retry(toggle_star, email_id, is_starred_state[0])

        async def on_archive(e, card_ref):
            async with ui_lock:
                email_list_view.controls.remove(card_ref)
                shown_email_ids.pop(email_id, None)
                all_emails[:] = [item for item in all_emails if item['id'] != email_id]
                fill_next_email()
            page.update()
            await _call_with_ssl_retry(archive_email, email_id)

        async def on_trash(e, card_ref):
            async with ui_lock:
                email_list_view.controls.remove(card_ref)
                shown_email_ids.pop(email_id, None)
                all_emails[:] = [item for item in all_emails if item['id'] != email_id]
                fill_next_email()
            page.update()
            await asyncio.to_thread(delete_analysis, email_id)
            await _call_with_ssl_retry(trash_email, email_id)

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
            margin=ft.Margin.symmetric(horizontal=10, vertical=3),
            content=ft.Container(
                bgcolor=card_bgcolor,
                padding=ft.Padding.only(left=15, right=4, top=4, bottom=12),
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
                                            padding=ft.Padding.all(2),
                                            tooltip="標記已讀",
                                            on_click=lambda e: page.run_task(on_mark_read, e),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.STAR if is_starred_state[0] else ft.Icons.STAR_BORDER,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            icon_color=ft.Colors.YELLOW_600,
                                            tooltip="加星號",
                                            on_click=lambda e: page.run_task(on_star, e, card),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.ARCHIVE,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            icon_color=ft.Colors.GREEN_400,
                                            tooltip="封存",
                                            on_click=lambda e: page.run_task(on_archive, e, card),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
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
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
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

    def _matches_view(data) -> bool:
        """Returns True if the email should appear in the current view."""
        if current_view[0] == "moodle":
            return is_moodle(data)
        return True  # inbox shows everything

    def render_current_view():
        """Rebuild the visible list from all_emails (sorted by _index), up to PAGE_SIZE."""
        email_list_view.controls.clear()
        shown_email_ids.clear()
        for data in all_emails:
            if len(shown_email_ids) >= PAGE_SIZE:
                break
            if not _matches_view(data):
                continue
            email_list_view.controls.append(create_email_card(data))
            shown_email_ids[data['id']] = data.get('_index', float('inf'))
        page.update()

    def fill_next_email():
        """After a card is removed, fill the empty slot with the next buffered email."""
        for data in all_emails:
            if data['id'] in shown_email_ids:
                continue
            if not _matches_view(data):
                continue
            email_list_view.controls.append(create_email_card(data))
            shown_email_ids[data['id']] = data.get('_index', float('inf'))
            return

    def switch_view(view: str):
        current_view[0] = view

        # Update sidebar selection
        for tile, name in sidebar_tiles:
            tile.selected = (name == view)

        # Update header
        if view == "inbox":
            header_icon.name = ft.Icons.INBOX
            header_title.value = "Inbox"
        elif view == "moodle":
            header_icon.name = ft.Icons.SCHOOL
            header_title.value = "Moodle"

        render_current_view()

    def get_next(gen):
        try:
            return next(gen)
        except StopIteration:
            return None

    def _insert_email_sorted(email_data):
        """Insert email into all_emails maintaining _index order."""
        new_idx = email_data.get('_index', float('inf'))
        for i, e in enumerate(all_emails):
            if e.get('_index', float('inf')) > new_idx:
                all_emails.insert(i, email_data)
                return
        all_emails.append(email_data)

    def append_email_to_view(email_data):
        """Insert one email card at the correct inbox position if the view isn't full yet."""
        if len(shown_email_ids) >= PAGE_SIZE:
            return  # page is full — keep in all_emails as buffer only
        if email_data['id'] in shown_email_ids:
            return
        if not _matches_view(email_data):
            return
        new_idx = email_data.get('_index', float('inf'))
        # Find insertion position: count shown emails with a smaller inbox index
        position = sum(1 for idx in shown_email_ids.values() if idx < new_idx)
        email_list_view.controls.insert(position, create_email_card(email_data))
        shown_email_ids[email_data['id']] = new_idx

    async def background_fetch_task(token, gen_id, page_num=2):
        """Silently fetches subsequent pages up to MAX_PAGES and appends to all_emails."""
        if page_num > MAX_PAGES:
            status_text.value = ""
            page.update()
            return
        try:
            gen = fetch_and_analyze_emails(svc["service"], page_token=token)
            while True:
                if fetch_gen[0] != gen_id:   # refresh was clicked — abort
                    return
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                if "_next_page_token" in email_data:
                    page.run_task(background_fetch_task, email_data["_next_page_token"], gen_id, page_num + 1)
                    return
                async with ui_lock:
                    _insert_email_sorted(email_data)
                    append_email_to_view(email_data)
                page.update()
                await asyncio.sleep(0)

            if fetch_gen[0] == gen_id:
                status_text.value = ""
                page.update()

        except Exception as ex:
            import traceback
            traceback.print_exc()
            if fetch_gen[0] == gen_id:
                status_text.value = f"背景載入失敗：{str(ex)}"
                page.update()

    async def fetch_task():
        this_gen = fetch_gen[0]
        try:
            if not svc["service"]:
                svc["service"] = await asyncio.to_thread(get_gmail_service)

                # Get User Gmail: xxxxx@gmail.com
                try:
                    profile = await asyncio.to_thread(svc["service"].users().getProfile(userId='me').execute)
                    user_email_text.value = profile.get('emailAddress', 'Unknown Email')
                except Exception as e:
                    print(f"[ERROR] Failed to fetch user profile: {e}")
                    user_email_text.value = "Offline Mode"

            stats = await asyncio.to_thread(get_inbox_stats, svc["service"])
            inbox_text.value   = str(stats["inbox"])
            unread_text.value  = str(stats["unread"])
            starred_text.value = str(stats["starred"])
            page.update()

            all_emails.clear()
            shown_email_ids.clear()
            email_list_view.controls.clear()
            page.update()

            gen = fetch_and_analyze_emails(svc["service"])
            while True:
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                if "_next_page_token" in email_data:
                    page.run_task(background_fetch_task, email_data["_next_page_token"], this_gen, 2)
                    return
                _insert_email_sorted(email_data)
                append_email_to_view(email_data)
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
        fetch_gen[0] += 1   # invalidate any running background tasks
        email_list_view.controls.clear()
        status_text.value = "Loading..."
        page.update()
        page.run_task(fetch_task)

    # ==========================
    # 4. Layout Assembly
    # ==========================

    tile_inbox = ft.ListTile(
        leading=ft.Icon(ft.Icons.INBOX), title=ft.Text("Inbox"), selected=True,
        on_click=lambda e: switch_view("inbox"),
    )
    tile_moodle = ft.ListTile(
        leading=ft.Icon(ft.Icons.SCHOOL), title=ft.Text("Moodle"),
        on_click=lambda e: switch_view("moodle"),
    )
    tile_announcements = ft.ListTile(leading=ft.Icon(ft.Icons.CAMPAIGN), title=ft.Text("Announcements"))
    tile_sent          = ft.ListTile(leading=ft.Icon(ft.Icons.SEND),      title=ft.Text("Sent"))
    tile_all           = ft.ListTile(leading=ft.Icon(ft.Icons.ALL_INBOX), title=ft.Text("All Mails"))
    tile_trash         = ft.ListTile(leading=ft.Icon(ft.Icons.DELETE),    title=ft.Text("Trash"))

    sidebar_tiles = [
        (tile_inbox, "inbox"),
        (tile_moodle, "moodle"),
    ]

    sidebar = ft.Container(
        width=250, bgcolor="#1e1e1e", padding=20,
        content=ft.Column([
            ft.Text("NCKU AInbox", size=26, weight="bold", color=ft.Colors.BLUE_200),
            user_email_text,
            ft.Divider(height=20),
            tile_inbox,
            tile_moodle,
            tile_announcements,
            ft.Divider(height=20),
            tile_sent,
            tile_all,
            tile_trash,
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
                                (header_icon := ft.Icon(ft.Icons.INBOX, size=28, color=ft.Colors.WHITE)),
                                (header_title := ft.Text("Inbox", size=30, weight="bold")),
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.Padding.only(left=10, right=10),
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