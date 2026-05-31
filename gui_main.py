import flet as ft
import os
import sys
import ssl
import bisect
import asyncio
import webbrowser
import calendar as _cal
import urllib.parse
from datetime import date as _date

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import (
    get_gmail_service, build_action_service,
    fetch_and_analyze_emails, fetch_simple_emails,
    get_inbox_stats, get_all_mail_stats,
)
from src.email_actions import mark_as_read, toggle_star, archive_email, trash_email, restore_email, permanent_delete_email
from src.db_manager import delete_analysis, get_detail_analysis, save_detail_analysis, get_cached_result
from src.email_parser import get_email_body
from src.ai_agent import analyze_email_detail
from src.calendar_db import init_calendar_db, add_event, event_exists, delete_event_by_key, delete_events_by_email_id, add_custom_event, delete_event
from src.calendar_view import build_calendar_months, CUSTOM_EVENT_COLORS
from src.settings.api_keys import build_api_keys_tab
from src.settings.preference import build_preference_tab
from src.settings.account import build_account_tab
from src.categories import (
    DEADLINE, HW_RELEASE, HW_CONFIRM, GRADE, CANCEL, EXAM_RELATED,
    IMPORTANT, LECTURE, ANNOUNCE, ADS, EXTERNAL, OTHER,
)

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

    # ensure calendar DB and table exist before any button handler can fire
    init_calendar_db()

    # ====================
    # Shared State
    # ====================

    # dict wrapper so every closure can reassign svc["service"] on SSL error
    svc = {"service": None}

    # ── All Mail / Inbox master list ──────────────────────────────────────────
    # All Mail is the canonical data source.  Inbox is a filtered view
    # (emails where is_in_inbox == True).  Both share these lists.
    all_emails      = []
    shown_email_ids = {}   # email_id → _index for currently rendered cards

    # ── Sent / Trash lightweight lists ───────────────────────────────────────
    sent_emails      = []
    trash_emails     = []
    sent_shown_ids   = {}
    trash_shown_ids  = {}
    view_loaded      = {"sent": False, "trash": False}

    current_view = "inbox"

    # incremented on each refresh — background tasks compare against this to self-cancel
    fetch_gen = 0

    # serializes UI mutations so background fetch and user actions don't collide
    ui_lock = asyncio.Lock()

    PAGE_SIZE = 50
    MAX_PAGES = 5   # maximum all-mail pages fetched in the background (50 emails each)

    # inbox-scoped counters; adjusted locally on every user action
    live_stats = {"inbox": 0, "unread": 0, "starred": 0}
    # all-mail counters (excludes trash/spam); adjusted locally on user actions
    all_mail_stats = {"total": 0, "unread": 0, "starred": 0}

    # ====================
    # Stats Bar
    # ====================

    # scrollable list that holds all visible email cards
    email_list_view = ft.ListView(expand=True, spacing=4, padding=ft.Padding.only(right=8))

    # shows the authenticated user's address under the app title
    user_email_text = ft.Text("Loading...", size=12, color=ft.Colors.OUTLINE)

    def _build_stats_bar():
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
                    tooltip="Total inbox",
                ),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.MARK_EMAIL_UNREAD, size=13, color=ft.Colors.BLUE_300),
                        ft.Text("--", size=12, color=ft.Colors.BLUE_300, weight=ft.FontWeight.BOLD),
                    ], spacing=3),
                    bgcolor="#2a2a2a", border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                    tooltip="Unread",
                ),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.STAR, size=13, color=ft.Colors.YELLOW_600),
                        ft.Text("--", size=12, color=ft.Colors.YELLOW_600, weight=ft.FontWeight.BOLD),
                    ], spacing=3),
                    bgcolor="#2a2a2a", border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                    tooltip="Starred",
                ),
            ],
            spacing=6,
        )

        # direct references to the number text nodes so fetch_task can update them
        inbox_text   = stats_row.controls[0].content.controls[1]
        unread_text  = stats_row.controls[1].content.controls[1]
        starred_text = stats_row.controls[2].content.controls[1]

        def update_stats_display():
            # hide stats bar entirely for Sent and Trash views
            if current_view in ("sent", "trash"):
                stats_container.visible = False
                page.update()
                return
            stats_container.visible = True

            if current_view == "inbox":
                # inbox: all three badges — total count is reliable here
                stats_row.controls[0].visible = True
                stats_row.controls[0].tooltip = "Total inbox"
                stats_row.controls[1].tooltip = "Unread"
                stats_row.controls[2].tooltip = "Starred (inbox)"
                inbox_text.value   = str(live_stats["inbox"])
                unread_text.value  = str(live_stats["unread"])
                starred_text.value = str(live_stats["starred"])
            elif current_view == "all_mail":
                # all mail: no total (resultSizeEstimate is unreliable) — unread + starred only
                stats_row.controls[0].visible = False
                stats_row.controls[1].tooltip = "Unread"
                stats_row.controls[2].tooltip = "Starred"
                unread_text.value  = str(all_mail_stats["unread"])
                starred_text.value = str(all_mail_stats["starred"])
            elif current_view == "moodle":
                # moodle: no total — unread + starred scoped to moodle emails
                stats_row.controls[0].visible = False
                stats_row.controls[1].tooltip = "Moodle unread"
                stats_row.controls[2].tooltip = "Moodle starred"
                moodle = [e for e in all_emails if "moodle" in e['sender'].lower()]
                unread_text.value  = str(sum(1 for e in moodle if e.get('is_unread')))
                starred_text.value = str(sum(1 for e in moodle if e.get('is_starred')))
            page.update()

        return update_stats_display, stats_row

    update_stats_display, stats_row = _build_stats_bar()

    # ====================
    # Email Detail Modal
    # ====================

    # header text nodes populated when the user double-taps a card
    modal_subject = ft.Text("", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, selectable=True)
    modal_sender  = ft.Text("", size=16, color=ft.Colors.BLUE_GREY_300)
    modal_time    = ft.Text("", size=16, color=ft.Colors.OUTLINE)

    def _on_gmail_btn_click(e):
        print(f"[GMAIL URL] {modal_gmail_btn.url}")

    modal_gmail_btn = ft.IconButton(
        icon=ft.Icons.OPEN_IN_NEW,
        icon_color=ft.Colors.BLUE_400,
        icon_size=22,
        tooltip="Open in Gmail",
        url="",
        on_click=_on_gmail_btn_click,
    )

    # raw content text node
    modal_body = ft.Text("", size=13, color="#dddddd", selectable=True)

    # incremented each time the modal opens — invalidates in-flight AI tasks from previous open
    modal_gen = 0

    # current active tab: "raw" or "ai"
    modal_view_state = "raw"

    # category of the currently open email (used by the calendar add button)
    modal_category = None

    # data dict of the currently open email (shared with the card so action buttons can mutate it)
    modal_data = [None]

    # authenticated Gmail address — fetched once and cached for building web URLs
    _gmail_user_email = ""

    def close_modal(e=None):
        nonlocal modal_gen
        modal_overlay.visible = False
        modal_gen += 1  # cancel any pending AI analysis task
        modal_data[0] = None
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
        padding=ft.Padding.all(8),
        border_radius=6,
        bgcolor=ft.Colors.BLUE_700,
        tooltip="Raw content",
        on_click=lambda e: switch_modal_tab("raw"),
    )
    modal_ai_tab = ft.Container(
        content=modal_ai_tab_icon,
        padding=ft.Padding.all(8),
        border_radius=6,
        bgcolor=None,
        tooltip="AI analysis",
        on_click=lambda e: switch_modal_tab("ai"),
    )

    def switch_modal_tab(tab):
        nonlocal modal_view_state
        modal_view_state       = tab
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
            padding=ft.Padding.only(right=14),
            spacing=8,
        ),
    )

    # ── AI analysis view ──
    # modal_ai_scroll is populated dynamically by _render_ai_result
    modal_ai_scroll = ft.ListView(expand=True, padding=ft.Padding.only(right=14), spacing=0)
    modal_ai_view = ft.Container(
        expand=True,
        visible=False,
        content=modal_ai_scroll,
    )

    def _render_ai_result(result, gen_id, email_id=None, category=None):
        """Rebuild the AI analysis panel. Silently ignored if the modal was closed/reopened."""
        if gen_id != modal_gen:
            return

        modal_ai_scroll.controls.clear()

        # ── still loading ──
        if result is None:
            modal_ai_scroll.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.ProgressRing(width=16, height=16, stroke_width=2),
                        ft.Text("Analyzing...", size=13, color=ft.Colors.OUTLINE),
                    ], spacing=8),
                    padding=ft.Padding.only(top=16),
                )
            )
            if modal_overlay.visible:
                page.update()
            return

        # ── analysis failed ──
        if result == "error":
            modal_ai_scroll.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=ft.Colors.RED_400),
                        ft.Text("AI analysis failed. Please try again.", size=13, color=ft.Colors.RED_400),
                    ], spacing=8),
                    padding=ft.Padding.only(top=16),
                )
            )
            if modal_overlay.visible:
                page.update()
            return

        # ── helper: section label with icon ──
        def section_header(icon, label):
            return ft.Container(
                content=ft.Row([
                    ft.Icon(icon, size=15, color=ft.Colors.BLUE_GREY_300),
                    ft.Text(label, size=15, color=ft.Colors.BLUE_GREY_300, weight=ft.FontWeight.BOLD),
                ], spacing=6),
                padding=ft.Padding.only(top=16, bottom=6),
            )

        # 摘要
        if result.get("summary"):
            modal_ai_scroll.controls += [
                section_header(ft.Icons.SUMMARIZE, "Summary"),
                ft.Container(
                    content=ft.Text(result["summary"], size=13, color="#dddddd", selectable=True),
                    padding=ft.Padding.only(left=8, bottom=4),
                ),
            ]

        # ── 待辦事項 ──
        if result.get("action_required"):
            modal_ai_scroll.controls += [
                section_header(ft.Icons.CHECK_CIRCLE_OUTLINE, "Action Items"),
                ft.Container(
                    content=ft.Text(result["action_required"], size=13, color=ft.Colors.ORANGE_200, selectable=True),
                    padding=ft.Padding.only(left=8, bottom=4),
                ),
            ]

        # ── 重要時間 ──
        if result.get("event_times"):
            modal_ai_scroll.controls.append(section_header(ft.Icons.EVENT, "Key Dates"))
            for item in result["event_times"]:
                lbl = item.get("label", "")
                t   = item.get("time", "")

                # check if already in calendar so the button reflects current state on open
                already_added = bool(email_id and event_exists(email_id, t))

                cal_btn = ft.IconButton(
                    icon=ft.Icons.EVENT_AVAILABLE if already_added else ft.Icons.CALENDAR_TODAY,
                    icon_size=14,
                    icon_color=ft.Colors.GREEN_400 if already_added else ft.Colors.BLUE_GREY_400,
                    tooltip="Added to calendar" if already_added else "Add to calendar",
                    style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                )

                def _on_add_to_cal(e, _lbl=lbl, _t=t, _eid=email_id, _cat=category, _btn=cal_btn):
                    if not _eid:
                        return
                    try:
                        if event_exists(_eid, _t):
                            # already in calendar — remove it
                            delete_event_by_key(_eid, _t)
                            _btn.icon       = ft.Icons.CALENDAR_TODAY
                            _btn.icon_color = ft.Colors.BLUE_GREY_400
                            _btn.tooltip    = "Add to calendar"
                            print(f"[CAL] Removed from calendar — {_lbl}: {_t}")
                        else:
                            # not in calendar — add it
                            add_event(_eid, _lbl, _t, source="manual", category=_cat)
                            _btn.icon       = ft.Icons.EVENT_AVAILABLE
                            _btn.icon_color = ft.Colors.GREEN_400
                            _btn.tooltip    = "Added to calendar"
                            print(f"[CAL] Added to calendar — {_lbl}: {_t}")
                        page.update()
                    except Exception as ex:
                        print(f"[CAL] Failed to toggle event: {ex}")

                cal_btn.on_click = _on_add_to_cal

                modal_ai_scroll.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.SCHEDULE, size=13, color=ft.Colors.ORANGE_300),
                            ft.Text(
                                f"{lbl}: {t}",
                                size=13, color=ft.Colors.ORANGE_300, selectable=True, expand=True,
                            ),
                            cal_btn,
                        ], spacing=6),
                        padding=ft.Padding.only(left=8, bottom=6),
                    )
                )

        # ── 相關連結 ──
        if result.get("urls"):
            modal_ai_scroll.controls.append(section_header(ft.Icons.LINK, "Related Links"))
            for item in result["urls"]:
                url = item.get("url", "")
                modal_ai_scroll.controls.append(
                    ft.GestureDetector(
                        mouse_cursor=ft.MouseCursor.CLICK,
                        on_tap=lambda e, u=url: webbrowser.open(u),
                        content=ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.OPEN_IN_NEW, size=13, color=ft.Colors.BLUE_300),
                                ft.Text(
                                    item.get("label") or url,
                                    size=13, color=ft.Colors.BLUE_300,
                                ),
                            ], spacing=6),
                            padding=ft.Padding.only(left=8, bottom=6),
                        ),
                    )
                )

        # ── 重點整理 ──
        if result.get("key_points"):
            modal_ai_scroll.controls.append(section_header(ft.Icons.PUSH_PIN, "Key Points"))
            for point in result["key_points"]:
                modal_ai_scroll.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text("•", size=13, color=ft.Colors.BLUE_GREY_300),
                            ft.Text(point, size=13, color="#dddddd", selectable=True, expand=True),
                        ], spacing=8),
                        padding=ft.Padding.only(left=8, bottom=6),
                    )
                )

        if modal_overlay.visible:
            page.update()

    async def _analyze_modal_email(email_id, body, gen_id):
        """Background task: serve detail analysis from DB cache or call AI if not cached."""
        cat = modal_category
        # check DB cache first — no AI call needed if already analyzed
        cached = await asyncio.to_thread(get_detail_analysis, email_id)
        if cached:
            _render_ai_result(cached, gen_id, email_id=email_id, category=cat)
            return

        _render_ai_result(None, gen_id, email_id=email_id, category=cat)  # show "analyzing…"
        try:
            result = await asyncio.to_thread(analyze_email_detail, body)
            if result:
                # persist so future opens are instant
                await asyncio.to_thread(save_detail_analysis, email_id, result)
                _render_ai_result(result, gen_id, email_id=email_id, category=cat)
            else:
                _render_ai_result("error", gen_id, email_id=email_id, category=cat)
        except Exception as ex:
            print(f"[WARN] Modal AI analysis failed: {ex}")
            _render_ai_result("error", gen_id, email_id=email_id, category=cat)

    async def _open_modal(data):
        """Open the email detail modal for any email data dict.
        Shared by inbox card double-tap and calendar event double-tap."""
        nonlocal modal_gen, modal_view_state, modal_category, _gmail_user_email
        email_id = data['id']

        modal_gen += 1
        this_gen = modal_gen

        # reset to raw tab, clear previous AI content
        modal_view_state       = "raw"
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
        modal_category        = data.get('category')
        modal_data[0]         = data

        # configure action buttons based on the current view
        if current_view == "trash":
            modal_star_btn.visible    = False
            modal_archive_btn.visible = True
            modal_archive_btn.icon       = ft.Icons.RESTORE_FROM_TRASH
            modal_archive_btn.icon_color = ft.Colors.GREEN_400
            modal_archive_btn.tooltip    = "Restore to Inbox"
            modal_trash_btn.visible   = True
            modal_trash_btn.icon      = ft.Icons.DELETE_FOREVER
            modal_trash_btn.tooltip   = "Permanent delete"
        elif current_view == "sent":
            modal_star_btn.visible    = False
            modal_archive_btn.visible = False
            modal_trash_btn.visible   = False
        else:
            modal_star_btn.visible    = True
            modal_archive_btn.visible = True
            modal_archive_btn.icon       = ft.Icons.ARCHIVE
            modal_archive_btn.icon_color = ft.Colors.GREEN_400
            modal_archive_btn.tooltip    = "Archive"
            modal_trash_btn.visible   = True
            modal_trash_btn.icon      = ft.Icons.DELETE
            modal_trash_btn.tooltip   = "Delete"

        # sync star button to the email's current star state
        _starred = data.get('is_starred', False)
        modal_star_btn.icon       = ft.Icons.STAR if _starred else ft.Icons.STAR_BORDER
        modal_star_btn.icon_color = ft.Colors.YELLOW_400 if _starred else ft.Colors.YELLOW_600
        modal_overlay.visible = True
        page.update()

        body = ""
        try:
            # mark as read in Gmail if still unread
            if data.get('is_unread'):
                data['is_unread'] = False
                live_stats["unread"]      = max(0, live_stats["unread"] - 1)
                all_mail_stats["unread"]  = max(0, all_mail_stats["unread"] - 1)
                update_stats_display()
                try:
                    await asyncio.to_thread(mark_as_read, svc["service"], email_id)
                except Exception as ex:
                    print(f"[WARN] Failed to mark as read: {ex}")

            # fresh service so it doesn't race with background fetch
            modal_service = await asyncio.to_thread(get_gmail_service)
            # fetch user email once and cache it — used to build the correct Gmail web URL
            if not _gmail_user_email:
                profile = await asyncio.to_thread(
                    modal_service.users().getProfile(userId="me").execute
                )
                _gmail_user_email = profile.get("emailAddress", "")

            msg_full = await asyncio.to_thread(
                modal_service.users().messages().get(userId="me", id=email_id, format="full").execute
            )

            # build Gmail web URL using authenticated email (bypasses u/N index problem)
            # and RFC 2822 Message-ID header (guaranteed to point to the exact email)
            headers = msg_full.get("payload", {}).get("headers", [])
            rfc822_id = next((h["value"] for h in headers if h["name"] == "Message-ID"), "")
            if _gmail_user_email and rfc822_id:
                encoded_id = urllib.parse.quote(rfc822_id, safe="")
                # AccountChooser selects the right Google account then redirects
                # to the Gmail search URL — avoids the u/N index problem entirely
                gmail_search = (
                    f"https://mail.google.com/mail/"
                    f"#search/rfc822msgid:{encoded_id}"
                )
                modal_gmail_btn.url = (
                    f"https://accounts.google.com/AccountChooser"
                    f"?Email={_gmail_user_email}"
                    f"&continue={urllib.parse.quote(gmail_search, safe='')}"
                )

            body = get_email_body(msg_full.get("payload", {}))
            modal_body.value = body.strip() if body and body.strip() else "(No readable content)"
        except Exception as ex:
            modal_body.value = f"(Failed to load email content: {ex})"
        finally:
            page.update()

        if body and body.strip():
            page.run_task(_analyze_modal_email, email_id, body.strip(), this_gen)

    # ── modal action buttons (star / archive / trash) ──
    modal_star_btn = ft.IconButton(
        icon=ft.Icons.STAR_BORDER,
        icon_size=20,
        icon_color=ft.Colors.YELLOW_600,
        tooltip="Star",
        padding=ft.Padding.all(2),
    )
    modal_archive_btn = ft.IconButton(
        icon=ft.Icons.ARCHIVE,
        icon_size=20,
        icon_color=ft.Colors.GREEN_400,
        tooltip="Archive",
        padding=ft.Padding.all(2),
    )
    modal_trash_btn = ft.IconButton(
        icon=ft.Icons.DELETE,
        icon_size=20,
        icon_color=ft.Colors.RED_400,
        tooltip="Delete",
        padding=ft.Padding.all(2),
    )

    async def _modal_on_star(e):
        data = modal_data[0]
        if data is None:
            return
        new_val = not data.get('is_starred', False)
        data['is_starred'] = new_val
        # update modal button
        modal_star_btn.icon = ft.Icons.STAR if new_val else ft.Icons.STAR_BORDER
        modal_star_btn.icon_color = ft.Colors.YELLOW_400 if new_val else ft.Colors.YELLOW_600
        # sync the card star button visible behind the transparent modal
        card_star = data.get('_star_btn_ref')
        if card_star:
            card_star.icon = ft.Icons.STAR if new_val else ft.Icons.STAR_BORDER
            card_star.icon_color = ft.Colors.YELLOW_400 if new_val else ft.Colors.YELLOW_600
        if new_val:
            live_stats["starred"]     += 1
            all_mail_stats["starred"] += 1
        else:
            live_stats["starred"]     = max(0, live_stats["starred"] - 1)
            all_mail_stats["starred"] = max(0, all_mail_stats["starred"] - 1)
        update_stats_display()
        await _call_with_ssl_retry(toggle_star, data['id'], new_val)

    async def _do_archive_email(data):
        """Archive: removes INBOX label.  Email stays in All Mail list; only
        disappears from Inbox view.  Does NOT delete DB records."""
        email_id     = data['id']
        was_in_inbox = data.get('is_in_inbox', True)
        async with ui_lock:
            data['is_in_inbox'] = False
            # remove card from view only when looking at the inbox filter
            if current_view == "inbox":
                card = data.get('_card_ref')
                if card and card in email_list_view.controls:
                    email_list_view.controls.remove(card)
                shown_email_ids.pop(email_id, None)
                fill_next_email()
            # adjust inbox-scoped counters only if the email actually had INBOX label
            if was_in_inbox:
                live_stats["inbox"] = max(0, live_stats["inbox"] - 1)
                if data.get('is_unread'):
                    live_stats["unread"]     = max(0, live_stats["unread"] - 1)
                    all_mail_stats["unread"] = max(0, all_mail_stats["unread"] - 1)
                if data.get('is_starred'):
                    live_stats["starred"] = max(0, live_stats["starred"] - 1)
                    # all_mail starred unchanged — email is still in All Mail
            update_stats_display()
        await asyncio.sleep(0)

    async def _do_trash_email(data):
        """Trash: removes email from All Mail entirely.  Deletes DB records."""
        email_id     = data['id']
        was_in_inbox = data.get('is_in_inbox', True)
        async with ui_lock:
            card = data.get('_card_ref')
            if card and card in email_list_view.controls:
                email_list_view.controls.remove(card)
            shown_email_ids.pop(email_id, None)
            all_emails[:] = [item for item in all_emails if item['id'] != email_id]
            fill_next_email()
            if was_in_inbox:
                live_stats["inbox"] = max(0, live_stats["inbox"] - 1)
                if data.get('is_unread'):
                    live_stats["unread"] = max(0, live_stats["unread"] - 1)
                if data.get('is_starred'):
                    live_stats["starred"]     = max(0, live_stats["starred"] - 1)
                    all_mail_stats["starred"] = max(0, all_mail_stats["starred"] - 1)
            if data.get('is_unread'):
                all_mail_stats["unread"] = max(0, all_mail_stats["unread"] - 1)
            all_mail_stats["total"] = max(0, all_mail_stats["total"] - 1)
            update_stats_display()
        await asyncio.sleep(0)
        await asyncio.to_thread(delete_analysis, email_id)
        await asyncio.to_thread(delete_events_by_email_id, email_id)

    async def _do_restore_email(data):
        """Restore: remove card from Trash view; the email moves back to Inbox."""
        email_id = data['id']
        async with ui_lock:
            card = data.get('_card_ref')
            if card and card in email_list_view.controls:
                email_list_view.controls.remove(card)
            trash_shown_ids.pop(email_id, None)
            trash_emails[:] = [item for item in trash_emails if item['id'] != email_id]
        await asyncio.sleep(0)

    async def _do_permanent_delete_email(data):
        """Permanent delete: remove card from Trash view and clean up DB."""
        email_id = data['id']
        async with ui_lock:
            card = data.get('_card_ref')
            if card and card in email_list_view.controls:
                email_list_view.controls.remove(card)
            trash_shown_ids.pop(email_id, None)
            trash_emails[:] = [item for item in trash_emails if item['id'] != email_id]
        await asyncio.sleep(0)
        await asyncio.to_thread(delete_analysis, email_id)
        await asyncio.to_thread(delete_events_by_email_id, email_id)

    async def _modal_on_archive(e):
        data = modal_data[0]
        if data is None:
            return
        close_modal()
        await asyncio.sleep(0)
        if current_view == "trash":
            await _do_restore_email(data)
            await _call_with_ssl_retry(restore_email, data['id'])
        else:
            await _do_archive_email(data)
            await _call_with_ssl_retry(archive_email, data['id'])

    async def _modal_on_trash(e):
        data = modal_data[0]
        if data is None:
            return
        close_modal()
        await asyncio.sleep(0)
        if current_view == "trash":
            await _do_permanent_delete_email(data)
            await _call_with_ssl_retry(permanent_delete_email, data['id'])
        else:
            await _do_trash_email(data)
            await _call_with_ssl_retry(trash_email, data['id'])

    modal_star_btn.on_click    = lambda e: page.run_task(_modal_on_star,    e)
    modal_archive_btn.on_click = lambda e: page.run_task(_modal_on_archive, e)
    modal_trash_btn.on_click   = lambda e: page.run_task(_modal_on_trash,   e)

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
                            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                            padding=ft.Padding.all(24),
                            content=ft.Column(
                                spacing=10,
                                expand=True,
                                controls=[
                                    # row 1: subject title (left) + action buttons (right)
                                    ft.Row(
                                        controls=[
                                            ft.Container(content=modal_subject, expand=True),
                                            ft.Row(
                                                controls=[modal_star_btn, modal_archive_btn, modal_trash_btn],
                                                spacing=0,
                                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                            ),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
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
                                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                                    # bottom bar: Gmail link (left) + tab switcher (right)
                                    ft.Row(
                                        controls=[
                                            modal_gmail_btn,
                                            ft.Container(expand=True),
                                            ft.Container(
                                                content=ft.Row(
                                                    controls=[modal_raw_tab, modal_ai_tab],
                                                    spacing=2,
                                                ),
                                                bgcolor="#2a2a2a",
                                                border_radius=8,
                                                padding=ft.Padding.all(3),
                                            ),
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
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

    async def _call_with_ssl_retry(fn, *args):
        """Call a Gmail API function using a FRESH service instance.

        Each action (delete, archive, star, mark-read) calls build_action_service()
        to obtain its own httplib2.Http connection pool.  This prevents the
        background email-fetch thread and action threads from sharing an SSL socket,
        which caused libmalloc heap corruption (EXC_BREAKPOINT / SIGTRAP) on macOS.
        """
        try:
            action_svc = await asyncio.to_thread(build_action_service)
            await asyncio.to_thread(fn, action_svc, *args)
        except (ssl.SSLError, OSError) as ex:
            if "SSL" not in str(ex) and not isinstance(ex, ssl.SSLError):
                raise
            print(f"[SSL] SSL error on action, retrying with new service... ({ex})")
            action_svc = await asyncio.to_thread(get_gmail_service)
            await asyncio.to_thread(fn, action_svc, *args)
        except Exception as ex:
            err = str(ex).lower()
            if "invalid_grant" in err or ("token" in err and "expired" in err):
                # Token revoked mid-session — re-auth and update main fetch service too
                print(f"[AUTH] Token revoked mid-session, re-authenticating... ({ex})")
                action_svc = await asyncio.to_thread(get_gmail_service)
                svc["service"] = action_svc   # refresh fetch service with new credentials
                await asyncio.to_thread(fn, action_svc, *args)
            else:
                raise

    # returns True if the email was sent from Moodle
    def is_moodle(data) -> bool:
        return "moodle" in data['sender'].lower()

    # maps AI category labels to badge background colors
    def get_tag_color(category: str):
        color_map = {
            DEADLINE:     ft.Colors.ORANGE_700,
            HW_RELEASE:   ft.Colors.BLUE_GREY_600,
            HW_CONFIRM:   ft.Colors.GREEN_700,
            GRADE:        ft.Colors.BLUE_700,
            CANCEL:       ft.Colors.PURPLE_700,
            EXAM_RELATED: ft.Colors.RED_700,
            IMPORTANT:    ft.Colors.RED_700,
            LECTURE:      ft.Colors.TEAL_700,
            ANNOUNCE:     ft.Colors.BLUE_400,
            ADS:          ft.Colors.BROWN_500,
            EXTERNAL:     ft.Colors.INDIGO_500,
            "Analysis Failed": ft.Colors.RED_900,
        }
        for key, color in color_map.items():
            if key in category:
                return color
        return ft.Colors.GREY_600

    # ====================
    # Email Card Builder
    # ====================

    def create_email_card(data, card_mode="default"):
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

        async def on_mark_read(e):
            # update card background color immediately before the API call
            if data.get('is_unread'):
                card_inner.bgcolor = "#2a2a2a"
                data['is_unread'] = False
                live_stats["unread"]     = max(0, live_stats["unread"] - 1)
                all_mail_stats["unread"] = max(0, all_mail_stats["unread"] - 1)
                update_stats_display()
            await _call_with_ssl_retry(mark_as_read, email_id)

        async def on_star(e, card_ref):
            # derive new value from data (authoritative) so modal sync cannot desync this
            new_val = not data.get('is_starred', False)
            is_starred_state[0] = new_val
            data['is_starred'] = new_val
            e.control.icon = ft.Icons.STAR if new_val else ft.Icons.STAR_BORDER
            e.control.icon_color = ft.Colors.YELLOW_400 if new_val else ft.Colors.YELLOW_600
            if new_val:
                live_stats["starred"]     += 1
                all_mail_stats["starred"] += 1
            else:
                live_stats["starred"]     = max(0, live_stats["starred"] - 1)
                all_mail_stats["starred"] = max(0, all_mail_stats["starred"] - 1)
            # sync modal star button if this card's modal is currently open
            if modal_overlay.visible and modal_data[0] is not None and modal_data[0]['id'] == email_id:
                modal_star_btn.icon = ft.Icons.STAR if new_val else ft.Icons.STAR_BORDER
                modal_star_btn.icon_color = ft.Colors.YELLOW_400 if new_val else ft.Colors.YELLOW_600
            update_stats_display()
            await _call_with_ssl_retry(toggle_star, email_id, new_val)

        async def on_archive(e, card_ref):
            await _do_archive_email(data)
            await _call_with_ssl_retry(archive_email, email_id)

        async def on_trash(e, card_ref):
            await _do_trash_email(data)
            await _call_with_ssl_retry(trash_email, email_id)

        async def on_restore(e, card_ref):
            await _do_restore_email(data)
            await _call_with_ssl_retry(restore_email, email_id)

        async def on_permanent_delete(e, card_ref):
            await _do_permanent_delete_email(data)
            await _call_with_ssl_retry(permanent_delete_email, email_id)

        async def on_tap(e):
            # update card read visual immediately (card_inner is local to this closure)
            if data.get('is_unread'):
                card_inner.bgcolor = "#2a2a2a"
            await _open_modal(data)

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

        # highlight emails whose content matches a saved preference keyword
        _matched = data.get('matched_prefs') or []
        _pref_border = ft.Border.all(2, ft.Colors.AMBER_400) if _matched else None

        # extracted so the modal can sync its icon via data['_star_btn_ref']
        _card_star_btn = ft.IconButton(
            icon=ft.Icons.STAR if is_starred_state[0] else ft.Icons.STAR_BORDER,
            icon_size=18,
            padding=ft.Padding.all(2),
            icon_color=ft.Colors.YELLOW_600,
            tooltip="Star",
            on_click=lambda e: page.run_task(on_star, e, card_ref[0]),
        )
        data['_star_btn_ref'] = _card_star_btn

        # stored as a named variable so on_double_tap can update its bgcolor
        card_inner = ft.Container(
            bgcolor=card_bgcolor,
            padding=ft.Padding.only(left=15, right=4, top=4, bottom=12),
            border_radius=10,
            border=_pref_border,
            content=ft.Column(
                spacing=8,
                controls=[
                    # top row: sender/title on the left, time + action buttons on the right
                    ft.Row(
                        controls=[
                            ft.Container(content=title_control, expand=True),
                            ft.Row(
                                controls=(
                                    # ── Trash view: Restore + Permanent Delete ──
                                    [
                                        ft.Text(data['time'], color=ft.Colors.OUTLINE, size=12),
                                        ft.IconButton(
                                            icon=ft.Icons.RESTORE_FROM_TRASH,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            icon_color=ft.Colors.GREEN_400,
                                            tooltip="Restore to Inbox",
                                            on_click=lambda e: page.run_task(on_restore, e, card_ref[0]),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE_FOREVER,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            icon_color=ft.Colors.RED_400,
                                            tooltip="Permanent delete",
                                            on_click=lambda e: page.run_task(on_permanent_delete, e, card_ref[0]),
                                        ),
                                    ] if card_mode == "trash" else
                                    # ── Sent view: read-only, time only ──
                                    [
                                        ft.Text(data['time'], color=ft.Colors.OUTLINE, size=12),
                                    ] if card_mode == "sent" else
                                    # ── Default (Inbox / All Mail / Moodle) ──
                                    [
                                        ft.Text(data['time'], color=ft.Colors.OUTLINE, size=12),
                                        ft.IconButton(
                                            icon=ft.Icons.MARK_EMAIL_READ,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            tooltip="Mark as read",
                                            on_click=lambda e: page.run_task(on_mark_read, e),
                                        ),
                                        _card_star_btn,
                                        ft.IconButton(
                                            icon=ft.Icons.ARCHIVE,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            icon_color=ft.Colors.GREEN_400,
                                            tooltip="Archive",
                                            on_click=lambda e: page.run_task(on_archive, e, card_ref[0]),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE,
                                            icon_size=18,
                                            padding=ft.Padding.all(2),
                                            icon_color=ft.Colors.RED_400,
                                            tooltip="Delete",
                                            on_click=lambda e: page.run_task(on_trash, e, card_ref[0]),
                                        ),
                                    ]
                                ),
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
            on_tap=lambda e: page.run_task(on_tap, e),
            content=card,
        )
        # fill the forward reference with the outermost widget —
        # email_list_view holds GestureDetectors, not Cards
        card_ref[0] = gesture
        # store in data so modal action buttons can remove the card without a lookup
        data['_card_ref'] = gesture
        return gesture

    # ====================
    # View Management
    # ====================

    # ── per-view helpers ──────────────────────────────────────────────────────

    def _active_lists():
        """Return (email_list, shown_ids_dict) for the current view."""
        if current_view in ("inbox", "all_mail", "moodle"):
            return all_emails, shown_email_ids
        if current_view == "sent":
            return sent_emails, sent_shown_ids
        if current_view == "trash":
            return trash_emails, trash_shown_ids
        return all_emails, shown_email_ids

    def _card_mode() -> str:
        if current_view == "trash":
            return "trash"
        if current_view == "sent":
            return "sent"
        return "default"

    # returns True if this email should be visible in the currently active view
    def _matches_view(data) -> bool:
        if current_view == "moodle":
            return is_moodle(data)
        if current_view == "inbox":
            return data.get("is_in_inbox", True)
        return True  # all_mail / sent / trash show every email in their list

    def render_current_view():
        """Rebuild the visible card list from scratch for the current view."""
        active_emails, active_shown = _active_lists()
        mode = _card_mode()
        email_list_view.controls.clear()
        active_shown.clear()
        for data in active_emails:
            if len(active_shown) >= PAGE_SIZE:
                break
            if not _matches_view(data):
                continue
            email_list_view.controls.append(create_email_card(data, card_mode=mode))
            active_shown[data['id']] = data.get('_index', float('inf'))
        update_stats_display()

    def fill_next_email():
        """When a card is removed, pull the next buffered email into view."""
        active_emails, active_shown = _active_lists()
        mode = _card_mode()
        for data in active_emails:
            if data['id'] in active_shown:
                continue
            if not _matches_view(data):
                continue
            email_list_view.controls.append(create_email_card(data, card_mode=mode))
            active_shown[data['id']] = data.get('_index', float('inf'))
            return

    def switch_view(view: str):
        nonlocal current_view
        current_view = view

        # highlight the selected sidebar tile
        for tile, name in sidebar_tiles:
            tile.selected = (name == view)

        # replace the ft.Icon object inside the wrapper (mutation of .name is unreliable in Flet)
        _icon_map = {
            "inbox":    (ft.Icons.INBOX,          "Inbox"),
            "moodle":   (ft.Icons.SCHOOL,         "Moodle"),
            "all_mail": (ft.Icons.ALL_INBOX,      "All Mail"),
            "sent":     (ft.Icons.SEND,           "Sent"),
            "trash":    (ft.Icons.DELETE,         "Trash"),
            "calendar": (ft.Icons.CALENDAR_MONTH, "Calendar"),
            "settings": (ft.Icons.SETTINGS,       "Settings"),
        }
        icon_name, title_text = _icon_map.get(view, (ft.Icons.INBOX, view.capitalize()))
        header_icon_wrapper.content = ft.Icon(icon_name, size=28, color=ft.Colors.WHITE)
        header_title.value = title_text

        # show only the relevant panel
        inbox_panel.visible       = view in ("inbox", "moodle", "all_mail", "sent", "trash")
        calendar_panel.visible    = view == "calendar"

        settings_panel.visible    = view == "settings"
        # hide refresh button for settings, sent, and trash (sent/trash re-fetch on each visit)
        header_refresh_btn.visible = view not in ("settings", "sent", "trash")

        if view in ("inbox", "moodle", "all_mail"):
            render_current_view()
            update_stats_display()
        elif view == "sent":
            page.run_task(_fetch_sent_task)
        elif view == "trash":
            page.run_task(_fetch_trash_task)
        elif view == "calendar":
            _refresh_calendar()
        elif view == "settings":
            page.run_task(_api_tab.auto_verify)

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
        keys = [e.get('_index', float('inf')) for e in all_emails]
        pos = bisect.bisect_left(keys, new_idx)
        all_emails.insert(pos, email_data)

    def append_email_to_view(email_data):
        """Insert one email card into the current view, respecting PAGE_SIZE."""
        active_emails, active_shown = _active_lists()
        mode = _card_mode()
        if len(active_shown) >= PAGE_SIZE:
            return
        if email_data['id'] in active_shown:
            return
        if not _matches_view(email_data):
            return
        new_idx  = email_data.get('_index', float('inf'))
        position = sum(1 for idx in active_shown.values() if idx < new_idx)
        email_list_view.controls.insert(position, create_email_card(email_data, card_mode=mode))
        active_shown[email_data['id']] = new_idx
        update_stats_display()

    # ====================
    # Fetch Tasks
    # ====================

    async def background_fetch_task(token, gen_id, page_num=2):
        # stop if we have already fetched the maximum allowed pages
        if page_num > MAX_PAGES:
            return
        try:
            gen = fetch_and_analyze_emails(svc["service"], page_token=token, page_offset=(page_num - 1) * PAGE_SIZE)
            while True:
                # abort if the user clicked refresh while this task was running
                if fetch_gen != gen_id:
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

    async def _fetch_simple_view_task(view_name: str, query: str,
                                      email_store: list, shown_store: dict):
        """Generic lightweight fetch for Sent / Trash views (metadata only, no AI).

        Uses build_action_service() to get a FRESH httplib2.Http connection pool
        so it never shares an SSL socket with the background All-Mail fetch task.
        """
        email_store.clear()
        shown_store.clear()
        email_list_view.controls.clear()
        page.update()
        try:
            view_svc = await asyncio.to_thread(build_action_service)
            gen = fetch_simple_emails(view_svc, query)
            idx = 0
            while True:
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                if "_next_page_token" in email_data:
                    break   # load first page only
                if current_view != view_name:
                    return  # user navigated away
                email_data["_index"] = idx
                idx += 1
                email_store.append(email_data)
                append_email_to_view(email_data)
                page.update()
                await asyncio.sleep(0)
        except Exception as ex:
            import traceback; traceback.print_exc()
            print(f"[ERROR] {view_name} fetch failed: {ex}")

    async def _fetch_sent_task():
        await _fetch_simple_view_task("sent",  "in:sent",  sent_emails,  sent_shown_ids)

    async def _fetch_trash_task():
        await _fetch_simple_view_task("trash", "in:trash", trash_emails, trash_shown_ids)

    async def fetch_task():
        this_gen = fetch_gen
        try:
            # build Gmail service only on the first run; reuse afterwards
            if not svc["service"]:
                # show a notice while the browser OAuth window may be opening
                email_list_view.controls.clear()
                email_list_view.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.ProgressRing(width=32, height=32, stroke_width=3),
                                ft.Text(
                                    "Connecting to Google — a browser window may open.",
                                    color=ft.Colors.BLUE_GREY_400,
                                    text_align=ft.TextAlign.CENTER,
                                    size=13,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=12,
                        ),
                        alignment=ft.Alignment(0, 0),
                        expand=True,
                        padding=ft.Padding.only(top=80),
                    )
                )
                page.update()

                svc["service"] = await asyncio.to_thread(get_gmail_service)

                if not svc["service"]:
                    email_list_view.controls.clear()
                    email_list_view.controls.append(
                        ft.Container(
                            content=ft.Text(
                                "Failed to connect to Gmail.",
                                color=ft.Colors.RED_400,
                                text_align=ft.TextAlign.CENTER,
                                size=13,
                            ),
                            alignment=ft.Alignment(0, 0),
                            expand=True,
                            padding=ft.Padding.only(top=80),
                        )
                    )
                    page.update()
                    return

                # fetch the authenticated user's email address for the sidebar
                try:
                    profile = await asyncio.to_thread(svc["service"].users().getProfile(userId='me').execute)
                    user_email_text.value = profile.get('emailAddress', 'Unknown Email')
                except Exception as e:
                    print(f"[ERROR] Failed to fetch user profile: {e}")
                    user_email_text.value = "Offline Mode"

            # guard: another refresh may have fired while we were initializing the service
            if fetch_gen != this_gen:
                return

            # update the stats badges — inbox-scoped first, then all-mail
            stats = await asyncio.to_thread(get_inbox_stats, svc["service"])
            if fetch_gen != this_gen:
                return
            live_stats["inbox"]   = stats["inbox"]
            live_stats["unread"]  = stats["unread"]
            live_stats["starred"] = stats["starred"]

            am_stats = await asyncio.to_thread(get_all_mail_stats, svc["service"])
            if fetch_gen != this_gen:
                return
            all_mail_stats["total"]   = am_stats["total"]
            all_mail_stats["unread"]  = am_stats["unread"]
            all_mail_stats["starred"] = am_stats["starred"]

            update_stats_display()

            # state was already cleared by on_refresh_click; clear again as a safety
            # net for the initial startup call where on_refresh_click runs synchronously
            all_emails.clear()
            shown_email_ids.clear()
            email_list_view.controls.clear()
            page.update()

            # stream page 1 — each yielded email is inserted and rendered immediately
            gen = fetch_and_analyze_emails(svc["service"])
            while True:
                # guard: abort immediately if the user clicked refresh again
                if fetch_gen != this_gen:
                    return
                email_data = await asyncio.to_thread(get_next, gen)
                if email_data is None:
                    break
                # re-check after the blocking call — refresh may have fired during get_next
                if fetch_gen != this_gen:
                    return
                # page 1 done — hand off remaining pages to a background task
                if "_next_page_token" in email_data:
                    page.run_task(background_fetch_task, email_data["_next_page_token"], this_gen, 2)
                    return
                async with ui_lock:
                    _insert_email_sorted(email_data)
                    append_email_to_view(email_data)
                page.update()
                await asyncio.sleep(0)

        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Fetch failed: {ex}")

    # ====================
    # Settings Controller
    # ====================

    def _build_settings_controller():
        _api_tab     = build_api_keys_tab(page)
        _pref_tab    = build_preference_tab(page)
        _account_tab = build_account_tab(page)

        settings_tab_state = ["preference"]

        def _settings_placeholder(label):
            return ft.Container(
                content=ft.Text(f"{label} coming soon…", size=16, color=ft.Colors.GREY_400),
                expand=True,
                alignment=ft.Alignment(0, 0),
            )

        settings_content = ft.Container(expand=True, content=_pref_tab.content)

        _TAB_DEFS = [
            ("preference",    "Preference",    ft.Icons.TUNE),
            ("appearance",    "Appearance",    ft.Icons.PALETTE),
            ("account",       "Account",       ft.Icons.MANAGE_ACCOUNTS),
            ("notifications", "Notifications", ft.Icons.NOTIFICATIONS),
            ("api_keys",      "API keys",      ft.Icons.KEY),
        ]

        def _stab_style(active: bool):
            return ft.ButtonStyle(
                color=ft.Colors.WHITE if active else ft.Colors.GREY_500,
                bgcolor={"": "#3a3a3a" if active else "transparent"},
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                shape=ft.RoundedRectangleBorder(radius=6),
            )

        _tab_content_map = {
            "preference": _pref_tab.content,
            "account":    _account_tab.content,
            "api_keys":   _api_tab.content,
        }

        def _settings_tab_btn(label, key, icon):
            def on_click(e):
                settings_tab_state[0] = key
                new_content = _tab_content_map.get(key)
                settings_content.content = new_content if new_content is not None else _settings_placeholder(label)
                for k, btn in _stab_btns.items():
                    btn.style = _stab_style(k == key)
                page.update()
            return ft.TextButton(
                on_click=on_click,
                style=_stab_style(key == settings_tab_state[0]),
                expand=True,
                content=ft.Row(
                    [
                        ft.Icon(icon, size=16),
                        ft.Text(label, size=13),
                    ],
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            )

        _stab_btns = {
            key: _settings_tab_btn(label, key, icon)
            for key, label, icon in _TAB_DEFS
        }

        settings_tab_bar = ft.Column(
            [
                ft.Container(
                    content=ft.Row(list(_stab_btns.values()), spacing=4, expand=True),
                    padding=ft.Padding.only(top=12, bottom=8),
                ),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Container(height=8),
            ],
            spacing=0,
        )

        settings_panel = ft.Column(
            expand=True,
            visible=False,
            spacing=0,
            controls=[settings_tab_bar, settings_content],
        )

        return settings_panel, _api_tab, _pref_tab

    settings_panel, _api_tab, _pref_tab = _build_settings_controller()
    page.on_close = lambda e: _api_tab.save_verified_on_close()

    def on_refresh_click(e):
        nonlocal fetch_gen
        # increment gen id — background tasks compare against this and self-cancel
        fetch_gen += 1
        # clear all state immediately so the UI is blank the instant the button is clicked
        all_emails.clear()
        shown_email_ids.clear()
        sent_emails.clear()
        sent_shown_ids.clear()
        trash_emails.clear()
        trash_shown_ids.clear()
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
    tile_calendar = ft.ListTile(
        leading=ft.Icon(ft.Icons.CALENDAR_MONTH), title=ft.Text("Calendar"),
        on_click=lambda e: switch_view("calendar"),
    )
    tile_sent  = ft.ListTile(
        leading=ft.Icon(ft.Icons.SEND),      title=ft.Text("Sent"),
        on_click=lambda e: switch_view("sent"),
    )
    tile_all   = ft.ListTile(
        leading=ft.Icon(ft.Icons.ALL_INBOX), title=ft.Text("All Mails"),
        on_click=lambda e: switch_view("all_mail"),
    )
    tile_trash = ft.ListTile(
        leading=ft.Icon(ft.Icons.DELETE),    title=ft.Text("Trash"),
        on_click=lambda e: switch_view("trash"),
    )
    tile_settings = ft.ListTile(
        leading=ft.Icon(ft.Icons.SETTINGS), title=ft.Text("Settings"),
        on_click=lambda e: switch_view("settings"),
    )

    sidebar_tiles = [
        (tile_inbox,    "inbox"),
        (tile_moodle,   "moodle"),
        (tile_all,      "all_mail"),
        (tile_sent,     "sent"),
        (tile_trash,    "trash"),
        (tile_calendar, "calendar"),
        (tile_settings, "settings"),
    ]

    sidebar = ft.Container(
        width=250, bgcolor="#1e1e1e", padding=20,
        content=ft.Column([
            ft.Text("NCKU AInbox", size=26, weight="bold", color=ft.Colors.BLUE_200),
            user_email_text,
            ft.Divider(height=20),
            tile_inbox,
            tile_moodle,
            tile_calendar,
            ft.Divider(height=20),
            tile_sent,
            tile_all,
            tile_trash,
            tile_settings,
        ])
    )

    # ====================
    # Calendar Controller
    # ====================

    def _build_calendar_controller():
        # scrollable inner list — rebuilt with fresh event data on every view switch
        cal_scroll = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)

        # ── Calendar Panel ───────────────────────────────────────────────────

        def _on_calendar_event_open(ev: dict):
            """Called when user double-taps a calendar event chip (receives full event dict)."""
            if ev.get("source") == "custom":
                _cv_open(ev)
                return
            # email-backed event — open the email detail modal
            email_id = ev["email_id"]
            data = next((e for e in all_emails if e['id'] == email_id), None)
            if data is None:
                cached = get_cached_result(email_id)
                if cached:
                    data = {
                        "id":        email_id,
                        "subject":   cached.get("summary") or "(No Subject)",
                        "sender":    cached.get("sender") or "Unknown",
                        "time":      cached.get("time") or "",
                        "category":  cached.get("category"),
                        "is_unread": False,
                    }
            if data:
                page.run_task(_open_modal, data)

        async def _scroll_to_current_month():
            await asyncio.sleep(0.1)
            await cal_scroll.scroll_to(scroll_key="current_month", duration=0)

        def _refresh_calendar(scroll_to_current=True):
            """Reload all events from DB and rebuild the calendar grid in cal_scroll."""
            page.update()   # flush panel visibility before the (slightly slow) build
            cal_scroll.controls = build_calendar_months(
                on_delete_event=_refresh_calendar,
                on_open_event=_on_calendar_event_open,
                on_create_event=_ce_open,
            )
            page.update()
            if scroll_to_current:
                page.run_task(_scroll_to_current_month)

        # ── Create Event Modal ───────────────────────────────────────────────

        _ce_date     = [""]
        _ce_all_day  = [False]
        _ce_color    = [CUSTOM_EVENT_COLORS[0]["id"]]
        _ce_dot_refs = {}

        _ce_date_label  = ft.Text("", size=13, color=ft.Colors.OUTLINE)
        _ce_title_field = ft.TextField(
            label="Title", hint_text="Event title…",
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.BLUE_400,
            text_style=ft.TextStyle(color=ft.Colors.WHITE),
        )
        _ce_notes_field = ft.TextField(
            hint_text="Add details…",
            multiline=True, min_lines=3, max_lines=5,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.BLUE_400,
            text_style=ft.TextStyle(color=ft.Colors.WHITE),
        )

        # ── dropdown time pickers: hours 00-23, minutes every 5 min ──
        _HOUR_OPTS   = [f"{h:02d}" for h in range(24)]
        _MINUTE_OPTS = [f"{m:02d}" for m in range(0, 60, 5)]

        def _make_time_dd(options, default):
            return ft.Dropdown(
                options=[ft.dropdown.Option(o) for o in options],
                value=default,
                width=85,
                bgcolor="#2a2a2a",
                border_color=ft.Colors.OUTLINE_VARIANT,
                focused_border_color=ft.Colors.BLUE_400,
                text_style=ft.TextStyle(color=ft.Colors.WHITE, size=14),
            )

        _ce_start_h_dd = _make_time_dd(_HOUR_OPTS,   "09")
        _ce_start_m_dd = _make_time_dd(_MINUTE_OPTS, "00")
        _ce_end_h_dd   = _make_time_dd(_HOUR_OPTS,   "10")
        _ce_end_m_dd   = _make_time_dd(_MINUTE_OPTS, "00")

        def _ce_time_group(label_text, h_dd, m_dd):
            return ft.Column([
                ft.Text(label_text, size=12, color=ft.Colors.OUTLINE),
                ft.Row([
                    h_dd,
                    ft.Text(":", size=16, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    m_dd,
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=6)

        _ce_time_row = ft.Row(
            [
                _ce_time_group("Start", _ce_start_h_dd, _ce_start_m_dd),
                ft.Container(expand=True),
                _ce_time_group("End",   _ce_end_h_dd,   _ce_end_m_dd),
            ],
            visible=True,
        )

        def _ce_btn_style(active: bool) -> ft.ButtonStyle:
            return ft.ButtonStyle(
                color=ft.Colors.WHITE if active else ft.Colors.GREY_500,
                bgcolor={"": "#3a3a3a" if active else "transparent"},
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                shape=ft.RoundedRectangleBorder(radius=6),
            )

        _ce_timed_btn  = ft.TextButton("Timed",   style=_ce_btn_style(True),  on_click=lambda e: _ce_toggle_allday(False))
        _ce_allday_btn = ft.TextButton("All day", style=_ce_btn_style(False), on_click=lambda e: _ce_toggle_allday(True))

        def _ce_toggle_allday(is_all_day: bool):
            _ce_all_day[0]       = is_all_day
            _ce_time_row.visible = not is_all_day
            _ce_timed_btn.style  = _ce_btn_style(not is_all_day)
            _ce_allday_btn.style = _ce_btn_style(is_all_day)
            page.update()

        def _ce_select_color(color_id: str):
            _ce_color[0] = color_id
            for cid, dot in _ce_dot_refs.items():
                dot.border = ft.Border.all(2, ft.Colors.WHITE) if cid == color_id else None
            page.update()

        # ── color dots: evenly spaced with SPACE_BETWEEN ──
        _ce_dot_controls = []
        for _c in CUSTOM_EVENT_COLORS:
            _dot = ft.Container(
                width=24, height=24, border_radius=12,
                bgcolor=_c["dot"],
                border=ft.Border.all(2, ft.Colors.WHITE) if _c["id"] == _ce_color[0] else None,
            )
            _ce_dot_refs[_c["id"]] = _dot
            _ce_dot_controls.append(
                ft.GestureDetector(
                    mouse_cursor=ft.MouseCursor.CLICK,
                    on_tap=lambda e, cid=_c["id"]: _ce_select_color(cid),
                    content=_dot,
                )
            )
        _ce_color_row = ft.Row(
            _ce_dot_controls,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        def _ce_close(e=None):
            create_event_overlay.visible = False
            page.update()

        def _ce_save(e):
            title = (_ce_title_field.value or "").strip()
            if not title:
                _ce_title_field.error_text = "Title is required"
                page.update()
                return
            _ce_title_field.error_text = None
            if _ce_all_day[0]:
                start_time, end_time = "", ""
            else:
                start_time = f"{_ce_start_h_dd.value}:{_ce_start_m_dd.value}"
                end_time   = f"{_ce_end_h_dd.value}:{_ce_end_m_dd.value}"
            add_custom_event(
                date_key   = _ce_date[0],
                title      = title,
                start_time = start_time,
                end_time   = end_time,
                is_all_day = _ce_all_day[0],
                color      = _ce_color[0],
                notes      = (_ce_notes_field.value or "").strip(),
            )
            _ce_close()
            # do NOT scroll back to current month — stay wherever the user was
            _refresh_calendar(scroll_to_current=False)

        def _ce_open(date_key: str):
            _ce_date[0]                = date_key
            _ce_date_label.value       = date_key
            _ce_title_field.value      = ""
            _ce_title_field.error_text = None
            _ce_notes_field.value      = ""
            _ce_start_h_dd.value = "09"; _ce_start_m_dd.value = "00"
            _ce_end_h_dd.value   = "10"; _ce_end_m_dd.value   = "00"
            _ce_toggle_allday(False)
            _ce_select_color(CUSTOM_EVENT_COLORS[0]["id"])
            create_event_overlay.visible = True
            page.update()

        create_event_overlay = ft.Stack(
            visible=False,
            expand=True,
            controls=[
                ft.Container(expand=True, bgcolor=ft.Colors.with_opacity(0.55, "#000000")),
                ft.GestureDetector(
                    on_tap=lambda e: _ce_close(),
                    content=ft.Container(
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        content=ft.GestureDetector(
                            on_tap=lambda e: None,   # absorb taps inside the box
                            content=ft.Container(
                                width=460,
                                bgcolor="#1e1e1e",
                                border_radius=14,
                                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                                padding=ft.Padding.all(24),
                                content=ft.Column(
                                    tight=True,
                                    spacing=16,
                                    # STRETCH makes every child fill the full column width
                                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                    controls=[
                                        # header
                                        ft.Row([
                                            ft.Text("New Event", size=18,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=ft.Colors.WHITE),
                                            ft.Container(expand=True),
                                            ft.IconButton(icon=ft.Icons.CLOSE,
                                                          icon_size=18, on_click=_ce_close),
                                        ]),
                                        # date label
                                        ft.Row([
                                            ft.Icon(ft.Icons.CALENDAR_TODAY,
                                                    size=14, color=ft.Colors.OUTLINE),
                                            _ce_date_label,
                                        ], spacing=6),
                                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                                        # title — stretches to full width via STRETCH
                                        _ce_title_field,
                                        # timed / all-day toggle
                                        ft.Row([_ce_timed_btn, _ce_allday_btn], spacing=4),
                                        # time dropdowns
                                        _ce_time_row,
                                        # color picker
                                        ft.Column([
                                            ft.Text("Color", size=12,
                                                    color=ft.Colors.OUTLINE),
                                            _ce_color_row,
                                        ], spacing=8),
                                        # "Notes" label above field so hint sits top-left
                                        ft.Column([
                                            ft.Text("Notes", size=12,
                                                    color=ft.Colors.OUTLINE),
                                            _ce_notes_field,
                                        ], spacing=6,
                                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                        # action buttons
                                        ft.Row([
                                            ft.Container(expand=True),
                                            ft.TextButton("Cancel", on_click=_ce_close),
                                            ft.Button(
                                                "Add Event", on_click=_ce_save,
                                                bgcolor=ft.Colors.BLUE_700,
                                                color=ft.Colors.WHITE,
                                            ),
                                        ]),
                                    ],
                                ),
                            ),
                        ),
                    ),
                ),
            ],
        )

        # ── Custom Event View ────────────────────────────────────────────────

        _cv_event      = [None]
        _cv_title_text = ft.Text("", size=17, weight=ft.FontWeight.BOLD,
                                 color=ft.Colors.WHITE, selectable=True)
        _cv_time_text  = ft.Text("", size=13, color=ft.Colors.OUTLINE)
        _cv_notes_text = ft.Text("", size=13, color="#dddddd", selectable=True)
        _cv_color_dot  = ft.Container(width=12, height=12, border_radius=6, bgcolor="#94a3b8")

        def _cv_close(e=None):
            ce_view_overlay.visible = False
            page.update()

        def _cv_delete(e):
            if _cv_event[0]:
                delete_event(_cv_event[0]["id"])
            _cv_close()
            _refresh_calendar()

        def _cv_open(ev: dict):
            _cv_event[0]         = ev
            _cv_title_text.value = ev.get("label", "")

            time_parts = []
            if ev.get("is_all_day"):
                time_parts.append("All day")
            else:
                tm = ev.get("event_time", "")
                # event_time is stored as "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"; split on space
                hm = tm.split(" ", 1)[1] if " " in tm else ""
                if hm:
                    time_parts.append(f"Start  {hm}")
                if ev.get("end_time"):
                    time_parts.append(f"End  {ev['end_time']}")
            _cv_time_text.value = "   ·   ".join(time_parts)

            c_entry = next(
                (c for c in CUSTOM_EVENT_COLORS if c["id"] == ev.get("color", "")),
                CUSTOM_EVENT_COLORS[-1]
            )
            _cv_color_dot.bgcolor = c_entry["dot"]
            _cv_notes_text.value  = ev.get("notes") or ""

            ce_view_overlay.visible = True
            page.update()

        ce_view_overlay = ft.Stack(
            visible=False,
            expand=True,
            controls=[
                ft.Container(expand=True, bgcolor=ft.Colors.with_opacity(0.55, "#000000")),
                ft.GestureDetector(
                    on_tap=lambda e: _cv_close(),
                    content=ft.Container(
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        content=ft.GestureDetector(
                            on_tap=lambda e: None,
                            content=ft.Container(
                                width=400,
                                bgcolor="#1e1e1e",
                                border_radius=14,
                                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                                padding=ft.Padding.all(24),
                                content=ft.Column(
                                    tight=True,
                                    spacing=14,
                                    controls=[
                                        ft.Row([
                                            _cv_color_dot,
                                            ft.Container(content=_cv_title_text,
                                                         expand=True,
                                                         padding=ft.Padding.only(left=8)),
                                            ft.IconButton(icon=ft.Icons.CLOSE,
                                                          icon_size=18, on_click=_cv_close),
                                        ], vertical_alignment=ft.CrossAxisAlignment.START),
                                        ft.Row([
                                            ft.Icon(ft.Icons.SCHEDULE, size=14,
                                                    color=ft.Colors.OUTLINE),
                                            _cv_time_text,
                                        ], spacing=6),
                                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                                        ft.Text("Notes", size=12, color=ft.Colors.OUTLINE),
                                        _cv_notes_text,
                                        ft.Row([
                                            ft.Container(expand=True),
                                            ft.TextButton(
                                                "Delete event",
                                                style=ft.ButtonStyle(color=ft.Colors.RED_400),
                                                on_click=_cv_delete,
                                            ),
                                        ]),
                                    ],
                                ),
                            ),
                        ),
                    ),
                ),
            ],
        )

        # ── Calendar widget assembly ─────────────────────────────────────────

        # sticky day-of-week header above the scrollable grid
        cal_header = ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text(
                        label, size=12, color=color,
                        weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    padding=ft.Padding.symmetric(vertical=6),
                )
                for label, color in [
                    ("Sun", ft.Colors.RED_300),
                    ("Mon", ft.Colors.BLUE_GREY_400),
                    ("Tue", ft.Colors.BLUE_GREY_400),
                    ("Wed", ft.Colors.BLUE_GREY_400),
                    ("Thu", ft.Colors.BLUE_GREY_400),
                    ("Fri", ft.Colors.BLUE_GREY_400),
                    ("Sat", ft.Colors.BLUE_300),
                ]
            ],
            spacing=2,
        )

        calendar_panel = ft.Column(
            expand=True,
            visible=False,
            spacing=0,
            controls=[
                cal_header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                cal_scroll,
            ],
        )

        return calendar_panel, create_event_overlay, ce_view_overlay

    calendar_panel, create_event_overlay, ce_view_overlay = _build_calendar_controller()

    # ====================
    # Main Content Area
    # ====================

    # wrap icon in a Container so we can swap the inner ft.Icon object reliably
    # (mutating ft.Icon.name alone does not always trigger a Flet re-render)
    header_icon_wrapper = ft.Container(
        content=ft.Icon(ft.Icons.INBOX, size=28, color=ft.Colors.WHITE)
    )
    header_title = ft.Text("Inbox", size=30, weight="bold")

    # wrapper that can be hidden for Sent / Trash views
    stats_container = ft.Container(
        content=stats_row,
        padding=ft.Padding.only(left=10),
        visible=True,
    )

    # inbox_panel wraps stats badges + email list — shared by inbox/all_mail/sent/trash
    inbox_panel = ft.Column(
        expand=True,
        visible=True,
        spacing=0,
        controls=[
            stats_container,
            ft.Divider(height=8, color="transparent"),
            email_list_view,
        ],
    )

    header_refresh_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_color=ft.Colors.BLUE_200,
        on_click=on_refresh_click,
    )

    main_content = ft.Container(
        expand=True, padding=30, bgcolor="#121212",
        content=ft.Column(
            expand=True,
            controls=[
                # top bar: header icon + title on the left, refresh button on the right
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            header_icon_wrapper,
                            header_title,
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding.only(left=10, right=10),
                    ),
                    header_refresh_btn,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                inbox_panel,
                calendar_panel,
                settings_panel,
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
                create_event_overlay,
                ce_view_overlay,
            ]
        )
    )

    # trigger the first fetch immediately on startup
    on_refresh_click(None)

if __name__ == "__main__":
    ft.run(main)
