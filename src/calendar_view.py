"""
calendar_view.py
Builds the calendar grid Flet controls, populated with events from calendar_db.
Called every time the user switches to the Calendar view so data is always fresh.
"""

import flet as ft
import calendar as _cal
import re as _re
from datetime import date as _date, timedelta

from src.calendar_db import get_all_events, delete_event

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _guess_year_for(month: int, day: int) -> str | None:
    """Return YYYY-MM-DD for a month/day with no year.
    Uses current year; bumps to next year if the date passed more than 30 days ago."""
    today = _date.today()
    try:
        candidate = _date(today.year, month, day)
        if candidate < today - timedelta(days=30):
            candidate = _date(today.year + 1, month, day)
        return candidate.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_date_key(event_time: str) -> str | None:
    """Extract a YYYY-MM-DD key from an event_time string.

    Handles all formats the AI commonly produces:
      YYYY-MM-DD [HH:MM]        e.g. "2026-04-20 23:59"
      YYYY/MM/DD [...]          e.g. "2026/04/20"
      YYYY年M月D日              e.g. "2026年4月20日"
      M月D日 [...]              e.g. "4月20日 18:00"
      M/D[(weekday)] [...]      e.g. "4/20(一) 18:00-20:00"
    Returns None if no recognisable date is found.
    """
    if not event_time:
        return None

    # YYYY-MM-DD
    m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', event_time)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # YYYY/MM/DD
    m = _re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', event_time)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # YYYY年M月D日
    m = _re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', event_time)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # M月D日  (no year)
    m = _re.search(r'(\d{1,2})月(\d{1,2})日', event_time)
    if m:
        return _guess_year_for(int(m.group(1)), int(m.group(2)))

    # M/D  or  M/D(weekday)  (no year) — must come after YYYY/MM/DD check
    m = _re.search(r'\b(\d{1,2})/(\d{1,2})\b', event_time)
    if m:
        return _guess_year_for(int(m.group(1)), int(m.group(2)))

    return None


# ---------------------------------------------------------------------------
# Event chip
# ---------------------------------------------------------------------------

def _event_chip(ev: dict, on_delete) -> ft.Control:
    """One clickable event row inside a day cell."""
    is_moodle = ev["source"] == "moodle_auto"
    # orange background for moodle auto-added, blue for manually added
    bg_color   = "#7c3a00" if is_moodle else "#0d3a6e"
    text_color = ft.Colors.ORANGE_200 if is_moodle else ft.Colors.BLUE_200

    # show category if available, otherwise fall back to label
    display_text = ev.get("category") or ev.get("label", "")

    # append time portion for compact display (e.g. "23:59")
    tm = _re.search(r'(\d{2}:\d{2})', ev["event_time"])
    if tm:
        display_text += f" {tm.group(1)}"

    def _delete(e, _id=ev["id"]):
        delete_event(_id)
        on_delete()   # caller rebuilds the calendar

    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    display_text,
                    size=10,
                    color=text_color,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                    expand=True,
                ),
                ft.GestureDetector(
                    mouse_cursor=ft.MouseCursor.CLICK,
                    on_tap=_delete,
                    content=ft.Icon(ft.Icons.CLOSE, size=10, color=text_color),
                ),
            ],
            spacing=3,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=4, vertical=2),
        border_radius=3,
        bgcolor=bg_color,
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_calendar_months(on_delete_event) -> list:
    """Return a list of Flet controls representing 14 months of calendar,
    with events from calendar_db shown inside each day cell.

    on_delete_event() is called after a user removes an event so the caller
    can rebuild the calendar panel.
    """
    today = _date.today()

    # index events by date key "YYYY-MM-DD"
    events_by_date: dict[str, list] = {}
    for ev in get_all_events():
        key = _parse_date_key(ev["event_time"])
        if key:
            events_by_date.setdefault(key, []).append(ev)

    sections = []

    for offset in range(14):
        raw   = today.month - 1 + offset
        year  = today.year + raw // 12
        month = raw % 12 + 1

        # month title
        sections.append(
            ft.Container(
                content=ft.Text(
                    f"{MONTH_NAMES[month - 1]} {year}",
                    size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE,
                ),
                padding=ft.Padding.only(top=20, bottom=8, left=4),
            )
        )

        # week rows
        for week in _cal.monthcalendar(year, month):
            # find the busiest day in this week to set row height for all cells
            max_events = max(
                len(events_by_date.get(f"{year:04d}-{month:02d}-{day:02d}", []))
                for day in week if day != 0
            ) if any(d != 0 for d in week) else 0

            # 80px fits exactly 2 chips; each extra event adds 22px
            # formula: 12px padding + 24px badge + 2px gap + N * (20px chip + 2px gap)
            cell_height = max(80, 36 + max_events * 22)

            cells = []
            for col, day in enumerate(week):
                is_sun = (col == 0)
                is_sat = (col == 6)

                if day == 0:
                    cells.append(
                        ft.Container(expand=True, height=cell_height, bgcolor="#161616", border_radius=6)
                    )
                    continue

                is_today = (year == today.year and month == today.month and day == today.day)

                if is_today:
                    num_color, num_bg = ft.Colors.WHITE, ft.Colors.BLUE_600
                elif is_sun:
                    num_color, num_bg = ft.Colors.RED_300, None
                elif is_sat:
                    num_color, num_bg = ft.Colors.BLUE_300, None
                else:
                    num_color, num_bg = ft.Colors.BLUE_GREY_300, None

                date_key = f"{year:04d}-{month:02d}-{day:02d}"
                day_events = events_by_date.get(date_key, [])

                event_chips = [
                    _event_chip(ev, on_delete_event)
                    for ev in day_events
                ]

                cells.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Container(
                                    content=ft.Text(
                                        str(day), size=12,
                                        color=num_color,
                                        weight=ft.FontWeight.BOLD,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    bgcolor=num_bg,
                                    border_radius=12,
                                    width=24, height=24,
                                    alignment=ft.Alignment(0, 0),
                                ),
                                *event_chips,
                            ],
                            spacing=2,
                        ),
                        expand=True,
                        height=cell_height,
                        bgcolor="#1e1e1e",
                        border_radius=6,
                        padding=ft.Padding.all(6),
                    )
                )

            sections.append(ft.Row(controls=cells, spacing=2))

        sections.append(ft.Divider(height=8, color="transparent"))

    return sections
