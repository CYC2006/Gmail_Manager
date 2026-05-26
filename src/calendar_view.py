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

# Color palette for user-created custom events.
# Excludes Moodle orange and lecture teal to preserve visual distinction.
CUSTOM_EVENT_COLORS = [
    {"id": "rose",   "dot": "#f87171", "bg": "#7f1d1d", "text": "#fca5a5"},
    {"id": "amber",  "dot": "#fbbf24", "bg": "#78350f", "text": "#fde68a"},
    {"id": "green",  "dot": "#4ade80", "bg": "#14532d", "text": "#86efac"},
    {"id": "purple", "dot": "#c084fc", "bg": "#581c87", "text": "#e9d5ff"},
    {"id": "pink",   "dot": "#f472b6", "bg": "#831843", "text": "#fbcfe8"},
    {"id": "slate",  "dot": "#94a3b8", "bg": "#1e293b", "text": "#cbd5e1"},
]
_COLOR_MAP = {c["id"]: c for c in CUSTOM_EVENT_COLORS}


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

def _event_chip(ev: dict, on_delete, on_open) -> ft.Control:
    """One clickable event row inside a day cell."""
    source = ev.get("source", "manual")

    if source == "custom":
        # user-created event: use chosen color, display title directly
        c_entry      = _COLOR_MAP.get(ev.get("color") or "", CUSTOM_EVENT_COLORS[-1])
        bg_color     = c_entry["bg"]
        text_color   = c_entry["text"]
        display_text = ev.get("label", "")
    else:
        # Moodle auto or manually added email event
        is_moodle  = source == "moodle_auto"
        bg_color   = "#7c3a00" if is_moodle else "#0d3a6e"
        text_color = ft.Colors.ORANGE_200 if is_moodle else ft.Colors.BLUE_200
        display_text = ev.get("category") or ev.get("label", "")

    # append time portion for compact display (e.g. "23:59")
    tm = _re.search(r'(\d{2}:\d{2})', ev["event_time"])
    if tm:
        display_text += f" {tm.group(1)}"

    def _delete(e, _id=ev["id"]):
        delete_event(_id)
        on_delete()

    def _open(e, _ev=ev):
        on_open(_ev)   # pass full event dict so caller can route custom vs email

    chip = ft.Container(
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

    # double-tap the chip to open the source email in the detail modal
    return ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.CLICK,
        on_double_tap=_open,
        content=chip,
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_calendar_months(on_delete_event, on_open_event, on_create_event=None) -> list:
    """Return a list of Flet controls for 14 months (Month-2 to Month+11).
    The current month's title container is tagged with key='current_month'
    for use with scroll_to(scroll_key='current_month').
    """
    today = _date.today()

    # index events by date key "YYYY-MM-DD"
    events_by_date: dict[str, list] = {}
    for ev in get_all_events():
        key = _parse_date_key(ev["event_time"])
        if key:
            events_by_date.setdefault(key, []).append(ev)

    sections = []

    # Build current + future months first (M+0 to M+11), then past months (M-2, M-1)
    # so the list always opens at the current month without needing scroll_to.
    for offset in range(-2, 12):  # M-2 to M+11 (14 months)
        raw   = today.month - 1 + offset
        year  = today.year + raw // 12
        month = raw % 12 + 1

        is_current = (year == today.year and month == today.month)
        sections.append(
            ft.Container(
                key=ft.ScrollKey("current_month") if is_current else None,
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
                    _event_chip(ev, on_delete_event, on_open_event)
                    for ev in day_events
                ]

                cell = ft.Container(
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
                # double-tap the cell to open the create-event modal
                cells.append(
                    ft.GestureDetector(
                        on_double_tap=(
                            (lambda e, dk=date_key: on_create_event(dk))
                            if on_create_event else None
                        ),
                        expand=True,
                        content=cell,
                    )
                )

            sections.append(ft.Row(controls=cells, spacing=2))

        sections.append(ft.Divider(height=8, color="transparent"))

    return sections
