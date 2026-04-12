import flet as ft
import os
import sys
import ssl
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import get_gmail_service, fetch_and_analyze_emails, get_inbox_stats
from src.email_actions import mark_as_read, toggle_star, archive_email, trash_email
from src.db_manager import delete_analysis, get_detail_analysis, save_detail_analysis
from src.email_parser import get_email_body
from src.ai_agent import analyze_email_detail

def main(page: ft.Page):

    # ====================
    # App Settings
    # ====================

    page.title = "NCKU Gmail Manager"
    page.window.width = 1100
    page.window.height = 700
    page.window.resizable = False
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    # ====================
    # Shared State
    # ====================

    # dict wrapper so every closure can reassign svc["service"] on SSL error
    svc = {"service": None}

    # master list of every fetched email (cached + AI-analyzed), sorted by inbox position
    all_emails = []

    # tracks which email ids are currently rendered and their inbox position (_index)
    shown_email_ids = {}

    # list wrapper to allow mutation inside closures without nonlocal
    current_view = ["inbox"]

    # incremented on each refresh — background tasks compare against this to self-cancel
    fetch_gen = [0]

    # serializes UI mutations so background fetch and user actions don't collide
    ui_lock = asyncio.Lock()

    PAGE_SIZE = 50
    MAX_PAGES = 5   # maximum inbox pages fetched in the background (50 emails each)

    # mirrors the API stats and is adjusted locally on every user action
    live_stats = {"inbox": 0, "unread": 0, "starred": 0}

    # ====================
    # Stats Bar
    # ====================

    # scrollable list that holds all visible email cards
    email_list_view = ft.ListView(expand=True, spacing=4, padding=ft.padding.only(right=8))

    # shows the authenticated user's address under the app title
    user_email_text = ft.Text("Loading...", size=12, color=ft.Colors.OUTLINE)

    # three badge chips: total inbox / unread / starred
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

    # direct references to the number text nodes so fetch_task can update them
    inbox_text   = stats_row.controls[0].content.controls[1]
    unread_text  = stats_row.controls[1].content.controls[1]
    starred_text = stats_row.controls[2].content.controls[1]

    def update_stats_display():
        # for inbox: use live_stats which mirrors the API count adjusted by user actions
        if current_view[0] == "inbox":
            stats_row.controls[0].tooltip = "Inbox 總數"
            stats_row.controls[1].tooltip = "未讀數"
            stats_row.controls[2].tooltip = "星號數"
            inbox_text.value   = str(live_stats["inbox"])
            unread_text.value  = str(live_stats["unread"])
            starred_text.value = str(live_stats["starred"])
        # for moodle: recount directly from all_emails filtered to moodle only
        elif current_view[0] == "moodle":
            stats_row.controls[0].tooltip = "Moodle 總數"
            stats_row.controls[1].tooltip = "Moodle 未讀數"
            stats_row.controls[2].tooltip = "Moodle 星號數"
            moodle = [e for e in all_emails if "moodle" in e['sender'].lower()]
            inbox_text.value   = str(len(moodle))
            unread_text.value  = str(sum(1 for e in moodle if e.get('is_unread')))
            starred_text.value = str(sum(1 for e in moodle if e.get('is_starred')))
        page.update()

    # ====================
    # Email Detail Modal
    # ====================

    # header text nodes populated when the user double-taps a card
    modal_subject = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, selectable=True)
    modal_sender  = ft.Text("", size=12, color=ft.Colors.BLUE_GREY_300)
    modal_time    = ft.Text("", size=12, color=ft.Colors.OUTLINE)

    # raw content text node
    modal_body = ft.Text("", size=13, color="#dddddd", selectable=True)

    # incremented each time the modal opens — invalidates in-flight AI tasks from previous open
    modal_gen = [0]

    # current active tab: "raw" or "ai"
    modal_view_state = ["raw"]

    def close_modal(e=None):
        modal_overlay.visible = False
        modal_gen[0] += 1  # cancel any pending AI analysis task
        page.update()

    # ── tab button styling helpers ──
    def _tab_on(icon_widget, container):
        container.bgcolor = ft.Colors.BLUE_700
        icon_widget.color = ft.Colors.WHITE

    def _tab_off(icon_widget, container):
        container.bgcolor = None
        icon_widget.color = ft.Colors.BLUE_GREY_400

    # tab button icon widgets (kept as references so color can be toggled)
    modal_raw_tab_icon = ft.Icon(ft.Icons.ARTICLE,       size=18, color=ft.Colors.WHITE)
    modal_ai_tab_icon  = ft.Icon(ft.Icons.AUTO_AWESOME,  size=18, color=ft.Colors.BLUE_GREY_400)

    modal_raw_tab = ft.Container(
        content=modal_raw_tab_icon,
        padding=ft.padding.all(8),
        border_radius=6,
        bgcolor=ft.Colors.BLUE_700,
        tooltip="原文內容",
        on_click=lambda e: switch_modal_tab("raw"),
    )
    modal_ai_tab = ft.Container(
        content=modal_ai_tab_icon,
        padding=ft.padding.all(8),
        border_radius=6,
        bgcolor=None,
        tooltip="信件分析",
        on_click=lambda e: switch_modal_tab("ai"),
    )

    def switch_modal_tab(tab):
        modal_view_state[0]    = tab
        modal_raw_view.visible = (tab == "raw")
        modal_ai_view.visible  = (tab == "ai")
        if tab == "raw":
            _tab_on(modal_raw_tab_icon, modal_raw_tab)
            _tab_off(modal_ai_tab_icon, modal_ai_tab)
        else:
            _tab_off(modal_raw_tab_icon, modal_raw_tab)
            _tab_on(modal_ai_tab_icon, modal_ai_tab)
        page.update()

    # ── raw content view ──
    # right padding keeps text clear of the scrollbar
    modal_raw_view = ft.Container(
        expand=True,
        visible=True,
        content=ft.ListView(
            controls=[modal_body],
            expand=True,
            padding=ft.padding.only(right=14),
            spacing=8,
        ),
    )

    # ── AI analysis view ──
    # modal_ai_scroll is populated dynamically by _render_ai_result
    modal_ai_scroll = ft.ListView(expand=True, padding=ft.padding.only(right=14), spacing=0)
    modal_ai_view = ft.Container(
        expand=True,
        visible=False,
        content=modal_ai_scroll,
    )

    def _render_ai_result(result, gen_id):
        """Rebuild the AI analysis panel. Silently ignored if the modal was closed/reopened."""
        if gen_id != modal_gen[0]:
            return

        modal_ai_scroll.controls.clear()

        # ── still loading ──
        if result is None:
            modal_ai_scroll.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.ProgressRing(width=16, height=16, stroke_width=2),
                        ft.Text("分析中...", size=13, color=ft.Colors.OUTLINE),
                    ], spacing=8),
                    padding=ft.padding.only(top=16),
                )
            )
            if modal_overlay.visible:
                page.update()
            return

        # ── analysis failed ──
        if result == "error":
            modal_ai_scroll.controls.append(
                ft.Text("AI 分析失敗，請稍後再試。", size=13, color=ft.Colors.RED_400)
            )
            if modal_overlay.visible:
                page.update()
            return

        # ── helper: dimmed section label with icon ──
        def section_header(icon, label):
            return ft.Container(
                content=ft.Row([
                    ft.Icon(icon, size=14, color=ft.Colors.BLUE_GREY_400),
                    ft.Text(label, size=12, color=ft.Colors.BLUE_GREY_400, weight=ft.FontWeight.BOLD),
                ], spacing=6),
                padding=ft.padding.only(top=12, bottom=4),
            )

        # ── summary ──
        if result.get("summary"):
            modal_ai_scroll.controls += [
                section_header(ft.Icons.SUMMARIZE, "摘要"),
                ft.Container(
                    content=ft.Text(result["summary"], size=13, color="#dddddd", selectable=True),
                    padding=ft.padding.only(left=4),
                ),
            ]

        # ── action required ──
        if result.get("action_required"):
            modal_ai_scroll.controls += [
                section_header(ft.Icons.CHECK_CIRCLE_OUTLINE, "待辦事項"),
                ft.Container(
                    content=ft.Text(result["action_required"], size=13, color=ft.Colors.ORANGE_200, selectable=True),
                    padding=ft.padding.only(left=4),
                ),
            ]

        # ── event times ──
        if result.get("event_times"):
            modal_ai_scroll.controls.append(section_header(ft.Icons.EVENT, "重要時間"))
            for item in result["event_times"]:
                modal_ai_scroll.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.SCHEDULE, size=13, color=ft.Colors.ORANGE_300),
                            ft.Text(
                                f"{item.get('label', '')}: {item.get('time', '')}",
                                size=13, color=ft.Colors.ORANGE_300, selectable=True,
                            ),
                        ], spacing=6),
                        padding=ft.padding.only(left=4, bottom=2),
                    )
                )

        # ── urls ──
        if result.get("urls"):
            modal_ai_scroll.controls.append(section_header(ft.Icons.LINK, "相關連結"))
            for item in result["urls"]:
                modal_ai_scroll.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.OPEN_IN_NEW, size=13, color=ft.Colors.BLUE_300),
                            ft.Text(
                                item.get("label") or item.get("url", ""),
                                size=13, color=ft.Colors.BLUE_300, selectable=True,
                            ),
                        ], spacing=6),
                        padding=ft.padding.only(left=4, bottom=2),
                    )
                )

        # ── key points ──
        if result.get("key_points"):
            modal_ai_scroll.controls.append(section_header(ft.Icons.PUSH_PIN, "重點整理"))
            for point in result["key_points"]:
                modal_ai_scroll.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text("•", size=13, color=ft.Colors.BLUE_GREY_300),
                            ft.Text(point, size=13, color="#dddddd", selectable=True, expand=True),
                        ], spacing=8),
                        padding=ft.padding.only(left=4, bottom=2),
                    )
                )

        if modal_overlay.visible:
            page.update()

    async def _analyze_modal_email(email_id, body, gen_id):
        """Background task: serve detail analysis from DB cache or call AI if not cached."""
        # check DB cache first — no AI call needed if already analyzed
        cached = await asyncio.to_thread(get_detail_analysis, email_id)
        if cached:
            _render_ai_result(cached, gen_id)
            return

        _render_ai_result(None, gen_id)  # show "analyzing…" while waiting for AI
        try:
            result = await asyncio.to_thread(analyze_email_detail, body)
            if result:
                # persist so future opens are instant
                await asyncio.to_thread(save_detail_analysis, email_id, result)
                _render_ai_result(result, gen_id)
            else:
                _render_ai_result("error", gen_id)
        except Exception as ex:
            print(f"[WARN] Modal AI analysis failed: {ex}")
            _render_ai_result("error", gen_id)

    # Stack layers (bottom → top):
    #   1. semi-transparent black backdrop (visual only)
    #   2. full-screen GestureDetector that closes modal on tap outside the box
    #      -> centered Container
    #         -> inner GestureDetector that absorbs taps inside the 720×540 box
    modal_overlay = ft.Stack(
        visible=False,
        expand=True,
        controls=[
            # 1. visual backdrop — no interaction, just the dim effect
            ft.Container(
                expand=True,
                bgcolor=ft.Colors.with_opacity(0.55, "#000000"),
            ),
            # 2. full-screen tap layer — closes modal when tapped outside the box
            ft.GestureDetector(
                on_tap=lambda e: close_modal(),
                content=ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    content=ft.GestureDetector(
                        # absorb taps so they don't bubble up to the close layer
                        on_tap=lambda e: None,
                        content=ft.Container(
                            width=720,
                            height=540,
                            bgcolor="#1e1e1e",
                            border_radius=14,
                            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                            padding=ft.Padding.all(24),
                            content=ft.Column(
                                spacing=10,
                                expand=True,
                                controls=[
                                    # row 1: subject title (close by clicking backdrop)
                                    modal_subject,
                                    # row 2: sender name (left) + received time (right)
                                    ft.Row(
                                        controls=[modal_sender, modal_time],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                                    # raw content view (default) — expands to fill remaining space
                                    modal_raw_view,
                                    # AI analysis view — hidden until user switches tab
                                    modal_ai_view,
                                    # bottom bar: tab switcher pinned at bottom-right
                                    ft.Row(
                                        controls=[
                                            ft.Container(expand=True),
                                            ft.Container(
                                                content=ft.Row(
                                                    controls=[modal_raw_tab, modal_ai_tab],
                                                    spacing=2,
                                                ),
                                                bgcolor="#2a2a2a",
                                                border_radius=8,
                                                padding=ft.padding.all(3),
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ),
                ),
            ),
        ],
    )

    # ====================
    # Email Card Helpers
    # ====================

    # returns True if the email was sent from Moodle
    def is_moodle(data) -> bool:
        return "moodle" in data['sender'].lower()

    # maps AI category labels to badge background colors
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

    # ====================
    # Email Card Builder
    # ====================

    def create_email_card(data):
        # unread emails get a lighter background to stand out
        card_bgcolor = "#444444" if data.get('is_unread') else "#2a2a2a"
        email_id = data['id']

        # list wrapper so the star handler can toggle the value inside a closure
        is_starred_state = [data.get('is_starred', False)]

        # list wrapper so archive/trash lambdas can reference card before it's created
        card_ref = [None]

        # --------------------
        # Card Action Handlers
        # --------------------

        async def _call_with_ssl_retry(fn, *args):
            # 1. try calling the Gmail API function normally
            try:
                await asyncio.to_thread(fn, svc["service"], *args)
            except (ssl.SSLError, OSError) as ex:
                if "SSL" not in str(ex) and not isinstance(ex, ssl.SSLError):
                    raise
                # 2. SSL connection went stale — rebuild the service and retry once
                print(f"[SSL] Connection stale, rebuilding service and retrying... ({ex})")
                svc["service"] = await asyncio.to_thread(get_gmail_service)
                await asyncio.to_thread(fn, svc["service"], *args)

        async def on_mark_read(e):
            # update card background color immediately before the API call
            if data.get('is_unread'):
                e.control.parent.parent.parent.parent.bgcolor = "#2a2a2a"
                data['is_unread'] = False
                live_stats["unread"] = max(0, live_stats["unread"] - 1)
                update_stats_display()
            await _call_with_ssl_retry(mark_as_read, email_id)

        async def on_star(e, card_ref):
            # toggle star state locally first for instant feedback
            is_starred_state[0] = not is_starred_state[0]
            e.control.icon = ft.Icons.STAR if is_starred_state[0] else ft.Icons.STAR_BORDER
            e.control.icon_color = ft.Colors.YELLOW_400 if is_starred_state[0] else ft.Colors.YELLOW_600
            data['is_starred'] = is_starred_state[0]
            if is_starred_state[0]:
                live_stats["starred"] += 1
            else:
                live_stats["starred"] = max(0, live_stats["starred"] - 1)
            update_stats_display()
            await _call_with_ssl_retry(toggle_star, email_id, is_starred_state[0])

        async def on_archive(e, card_ref):
            async with ui_lock:
                # remove card from view and buffer, then fill the empty slot
                email_list_view.controls.remove(card_ref)
                shown_email_ids.pop(email_id, None)
                all_emails[:] = [item for item in all_emails if item['id'] != email_id]
                fill_next_email()
            # adjust counts for the removed email
            live_stats["inbox"] = max(0, live_stats["inbox"] - 1)
            if data.get('is_unread'):
                live_stats["unread"] = max(0, live_stats["unread"] - 1)
            if data.get('is_starred'):
                live_stats["starred"] = max(0, live_stats["starred"] - 1)
            update_stats_display()
            await _call_with_ssl_retry(archive_email, email_id)

        async def on_trash(e, card_ref):
            async with ui_lock:
                # remove card from view and buffer, then fill the empty slot
                email_list_view.controls.remove(card_ref)
                shown_email_ids.pop(email_id, None)
                all_emails[:] = [item for item in all_emails if item['id'] != email_id]
                fill_next_email()
            # adjust counts for the removed email
            live_stats["inbox"] = max(0, live_stats["inbox"] - 1)
            if data.get('is_unread'):
                live_stats["unread"] = max(0, live_stats["unread"] - 1)
            if data.get('is_starred'):
                live_stats["starred"] = max(0, live_stats["starred"] - 1)
            update_stats_display()
            # remove from local cache before trashing on Gmail
            await asyncio.to_thread(delete_analysis, email_id)
            await _call_with_ssl_retry(trash_email, email_id)

        async def on_double_tap(e):
            # new open — increment generation to invalidate any previous AI task
            modal_gen[0] += 1
            this_gen = modal_gen[0]

            # reset to raw tab, clear previous AI content
            modal_view_state[0]    = "raw"
            modal_raw_view.visible = True
            modal_ai_view.visible  = False
            _tab_on(modal_raw_tab_icon, modal_raw_tab)
            _tab_off(modal_ai_tab_icon, modal_ai_tab)
            modal_ai_scroll.controls.clear()

            # populate modal header and show it immediately
            modal_subject.value   = data['subject']
            modal_sender.value    = data['sender']
            modal_time.value      = data['time']
            modal_body.value      = ""
            modal_overlay.visible = True
            page.update()

            body = ""
            try:
                # only mark as read if the mail is currently unread
                if data.get('is_unread'):
                    card_inner.bgcolor = "#2a2a2a"
                    data['is_unread'] = False
                    live_stats["unread"] = max(0, live_stats["unread"] - 1)
                    update_stats_display()
                    try:
                        await _call_with_ssl_retry(mark_as_read, email_id)
                    except Exception as ex:
                        print(f"[WARN] 標示已讀失敗: {ex}")

                # build a fresh service with its own SSL connection so it doesn't
                # race with the background fetch that shares svc["service"]
                modal_service = await asyncio.to_thread(get_gmail_service)
                # fetch the full email (not just metadata)
                msg_full = await asyncio.to_thread(
                    modal_service.users().messages().get(userId="me", id=email_id, format="full").execute
                )
                # decode plain-text body from MIME payload
                body = get_email_body(msg_full.get("payload", {}))
                modal_body.value = body.strip() if body and body.strip() else "(No readable content)"
            except Exception as ex:
                modal_body.value = f"(Failed to load email content: {ex})"
            finally:
                # always refresh, even if something crashed
                page.update()

            # kick off AI analysis in background with the fetched body
            # serves from DB cache if already analyzed; runs AI only on first open
            if body and body.strip():
                page.run_task(_analyze_modal_email, email_id, body.strip(), this_gen)

        # --------------------
        # Card Layout
        # --------------------

        # Moodle emails show an icon + "Moodle" label instead of the sender name
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

        # stored as a named variable so on_double_tap can update its bgcolor
        card_inner = ft.Container(
            bgcolor=card_bgcolor,
            padding=ft.Padding.only(left=15, right=4, top=4, bottom=12),
            border_radius=10,
            content=ft.Column(
                spacing=8,
                controls=[
                    # top row: sender/title on the left, time + action buttons on the right
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
                                        on_click=lambda e: page.run_task(on_star, e, card_ref[0]),
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.ARCHIVE,
                                        icon_size=18,
                                        padding=ft.Padding.all(2),
                                        icon_color=ft.Colors.GREEN_400,
                                        tooltip="封存",
                                        on_click=lambda e: page.run_task(on_archive, e, card_ref[0]),
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE,
                                        icon_size=18,
                                        padding=ft.Padding.all(2),
                                        icon_color=ft.Colors.RED_400,
                                        tooltip="刪除",
                                        on_click=lambda e: page.run_task(on_trash, e, card_ref[0]),
                                    ),
                                ],
                                spacing=0,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # bottom row: colored category badge + raw email subject
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(data['category'], size=13, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, no_wrap=True),
                                bgcolor=get_tag_color(data['category']),
                                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                border_radius=5,
                            ),
                            ft.Text(data['subject'], size=13, expand=True, color="#bbbbbb", overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
            ),
        )
        card = ft.Card(
            margin=ft.Margin.symmetric(horizontal=10, vertical=3),
            content=card_inner,
        )
        gesture = ft.GestureDetector(
            on_double_tap=lambda e: page.run_task(on_double_tap, e),
            content=card,
        )
        # fill the forward reference with the outermost widget —
        # email_list_view holds GestureDetectors, not Cards
        card_ref[0] = gesture
        return gesture

    # ====================
    # View Management
    # ====================

    # returns True if this email belongs in the currently active sidebar view
    def _matches_view(data) -> bool:
        if current_view[0] == "moodle":
            return is_moodle(data)
        return True  # inbox shows all emails

    def render_current_view():
        # rebuild the visible card list from scratch whenever the view changes
        email_list_view.controls.clear()
        shown_email_ids.clear()
        for data in all_emails:
            if len(shown_email_ids) >= PAGE_SIZE:
                break
            if not _matches_view(data):
                continue
            email_list_view.controls.append(create_email_card(data))
            shown_email_ids[data['id']] = data.get('_index', float('inf'))
        update_stats_display()

    def fill_next_email():
        # when a card is removed (archived/trashed), pull the next buffered email into view
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

        # highlight the selected sidebar tile
        for tile, name in sidebar_tiles:
            tile.selected = (name == view)

        # update the header icon and title to match the selected view
        if view == "inbox":
            header_icon.name = ft.Icons.INBOX
            header_title.value = "Inbox"
        elif view == "moodle":
            header_icon.name = ft.Icons.SCHOOL
            header_title.value = "Moodle"

        render_current_view()
        update_stats_display()

    # ====================
    # Email List Helpers
    # ====================

    # safe wrapper around next() — returns None when the generator is exhausted
    def get_next(gen):
        try:
            return next(gen)
        except StopIteration:
            return None

    def _insert_email_sorted(email_data):
        # keep all_emails ordered by _index (original inbox position)
        new_idx = email_data.get('_index', float('inf'))
        for i, e in enumerate(all_emails):
            if e.get('_index', float('inf')) > new_idx:
                all_emails.insert(i, email_data)
                return
        all_emails.append(email_data)

    def append_email_to_view(email_data):
        # skip if the visible page is already full — email stays buffered in all_emails
        if len(shown_email_ids) >= PAGE_SIZE:
            return
        if email_data['id'] in shown_email_ids:
            return
        if not _matches_view(email_data):
            return
        # insert at the correct position based on inbox order
        new_idx = email_data.get('_index', float('inf'))
        position = sum(1 for idx in shown_email_ids.values() if idx < new_idx)
        email_list_view.controls.insert(position, create_email_card(email_data))
        shown_email_ids[email_data['id']] = new_idx
        update_stats_display()

    # ====================
    # Fetch Tasks
    # ====================

    async def background_fetch_task(token, gen_id, page_num=2):
        # stop if we have already fetched the maximum allowed pages
        if page_num > MAX_PAGES:
            return
        try:
            gen = fetch_and_analyze_emails(svc["service"], page_token=token)
            while True:
                # abort if the user clicked refresh while this task was running
                if fetch_gen[0] != gen_id:
                    return
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                # if there is another page, chain a new background task and exit this one
                if "_next_page_token" in email_data:
                    page.run_task(background_fetch_task, email_data["_next_page_token"], gen_id, page_num + 1)
                    return
                async with ui_lock:
                    _insert_email_sorted(email_data)
                    append_email_to_view(email_data)
                page.update()
                await asyncio.sleep(0)

        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Background fetch failed: {ex}")

    async def fetch_task():
        this_gen = fetch_gen[0]
        try:
            # build Gmail service only on the first run; reuse afterwards
            if not svc["service"]:
                svc["service"] = await asyncio.to_thread(get_gmail_service)

                # fetch the authenticated user's email address for the sidebar
                try:
                    profile = await asyncio.to_thread(svc["service"].users().getProfile(userId='me').execute)
                    user_email_text.value = profile.get('emailAddress', 'Unknown Email')
                except Exception as e:
                    print(f"[ERROR] Failed to fetch user profile: {e}")
                    user_email_text.value = "Offline Mode"

            # update the stats badges (inbox total / unread / starred)
            stats = await asyncio.to_thread(get_inbox_stats, svc["service"])
            live_stats["inbox"]   = stats["inbox"]
            live_stats["unread"]  = stats["unread"]
            live_stats["starred"] = stats["starred"]
            update_stats_display()

            # clear previous results before loading the fresh batch
            all_emails.clear()
            shown_email_ids.clear()
            email_list_view.controls.clear()
            page.update()

            # stream page 1 — each yielded email is inserted and rendered immediately
            gen = fetch_and_analyze_emails(svc["service"])
            while True:
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                # page 1 done — hand off remaining pages to a background task
                if "_next_page_token" in email_data:
                    page.run_task(background_fetch_task, email_data["_next_page_token"], this_gen, 2)
                    return
                _insert_email_sorted(email_data)
                append_email_to_view(email_data)
                page.update()
                await asyncio.sleep(0)

        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Fetch failed: {ex}")

    def on_refresh_click(e):
        # increment gen id to cancel any in-progress background fetch tasks
        fetch_gen[0] += 1
        email_list_view.controls.clear()
        page.update()
        page.run_task(fetch_task)

    # ====================
    # Sidebar
    # ====================

    tile_inbox = ft.ListTile(
        leading=ft.Icon(ft.Icons.INBOX), title=ft.Text("Inbox"), selected=True,
        on_click=lambda e: switch_view("inbox"),
    )
    tile_moodle = ft.ListTile(
        leading=ft.Icon(ft.Icons.SCHOOL), title=ft.Text("Moodle"),
        on_click=lambda e: switch_view("moodle"),
    )
    # placeholder tiles — not yet wired to any view
    tile_announcements = ft.ListTile(leading=ft.Icon(ft.Icons.CAMPAIGN), title=ft.Text("Announcements"))
    tile_sent          = ft.ListTile(leading=ft.Icon(ft.Icons.SEND),      title=ft.Text("Sent"))
    tile_all           = ft.ListTile(leading=ft.Icon(ft.Icons.ALL_INBOX), title=ft.Text("All Mails"))
    tile_trash         = ft.ListTile(leading=ft.Icon(ft.Icons.DELETE),    title=ft.Text("Trash"))

    # only tiles with an active view need to be in this list for selection highlighting
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

    # ====================
    # Main Content Area
    # ====================

    main_content = ft.Container(
        expand=True, padding=30, bgcolor="#121212",
        content=ft.Column(
            expand=True,
            controls=[
                # top bar: header icon + title on the left, refresh button on the right
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            (header_icon := ft.Icon(ft.Icons.INBOX, size=28, color=ft.Colors.WHITE)),
                            (header_title := ft.Text("Inbox", size=30, weight="bold")),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding.only(left=10, right=10),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        icon_color=ft.Colors.BLUE_200,
                        on_click=on_refresh_click,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                # stats badges sit below the title
                ft.Container(
                    content=stats_row,
                    padding=ft.Padding.only(left=10),
                ),
                ft.Divider(height=0, color="transparent"),
                email_list_view,
            ]
        )
    )

    # ====================
    # Page Assembly
    # ====================

    # Stack puts the modal overlay on top of the entire sidebar + content layout
    page.add(
        ft.Stack(
            expand=True,
            controls=[
                ft.Row(
                    expand=True,
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        sidebar,
                        ft.VerticalDivider(width=1, color=ft.Colors.OUTLINE_VARIANT),
                        main_content,
                    ]
                ),
                modal_overlay,
            ]
        )
    )

    # trigger the first fetch immediately on startup
    on_refresh_click(None)

if __name__ == "__main__":
    ft.app(target=main)
