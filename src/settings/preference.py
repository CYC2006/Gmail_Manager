"""
preference.py
Builds the Preference settings tab — Interests & Hobbies only.
"""

import json
import os
from types import SimpleNamespace

import flet as ft

from src.config_manager import get_selected_interests, save_selected_interests

_OPTIONS_FILE = os.path.join(os.path.dirname(__file__), "preference_options.json")


def _load_options() -> dict:
    try:
        with open(_OPTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[PREF] Failed to load preference options: {e}")
        return {}


def build_preference_tab(page: ft.Page) -> SimpleNamespace:
    options = _load_options()

    # ---- state ----
    _selected_ids:    set[str] = set(get_selected_interests())
    _saved_interests: list[set] = [set(_selected_ids)]

    # ---- save button (declared early so helpers can reference it) ----
    _save_btn = ft.ElevatedButton(
        "Save",
        icon=ft.Icons.SAVE,
        disabled=True,
        style=ft.ButtonStyle(
            bgcolor={"": ft.Colors.GREY_800},
            color={"": ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        ),
    )

    # ---- chip grid layout constants ----
    # Chips use expand=True + spacing=4 to mirror the settings tab bar exactly,
    # so every chip column aligns with the tab buttons above it.
    _CHIPS_PER_ROW = 5
    _CHIP_SPACING  = 4

    # ---- helpers ----

    def _update_save_btn():
        changed = _selected_ids != _saved_interests[0]
        _save_btn.disabled = not changed
        _save_btn.style = ft.ButtonStyle(
            bgcolor={"": ft.Colors.BLUE_700 if changed else ft.Colors.GREY_800},
            color={"": ft.Colors.WHITE   if changed else ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        page.update()

    # ---- icon mapping (one Material icon per interest id) ----
    _INTEREST_ICONS: dict[str, str] = {
        "ai_ml":          ft.Icons.PSYCHOLOGY,
        "mobile":         ft.Icons.PHONE_ANDROID,
        "webdev":         ft.Icons.WEB,
        "coding_hobby":   ft.Icons.CODE,
        "opensource":     ft.Icons.HUB,
        "gaming":         ft.Icons.SPORTS_ESPORTS,
        "anime":          ft.Icons.COLLECTIONS,
        "boardgame":      ft.Icons.EXTENSION,
        "crypto":         ft.Icons.MONETIZATION_ON,
        "investing":      ft.Icons.SHOW_CHART,
        "startup":        ft.Icons.ROCKET_LAUNCH,
        "science":        ft.Icons.SCIENCE,
        "politics":       ft.Icons.ACCOUNT_BALANCE,
        "language":       ft.Icons.TRANSLATE,
        "sustainability": ft.Icons.ECO,
        "volunteering":   ft.Icons.VOLUNTEER_ACTIVISM,
        "sports":         ft.Icons.SPORTS,
        "film":           ft.Icons.MOVIE,
        "literature":     ft.Icons.MENU_BOOK,
        "writing":        ft.Icons.EDIT,
        "theater":        ft.Icons.THEATER_COMEDY,
        "music":          ft.Icons.MUSIC_NOTE,
        "instrument":     ft.Icons.PIANO,
        "singing":        ft.Icons.MIC,
        "drawing":        ft.Icons.BRUSH,
        "video_edit":     ft.Icons.MOVIE_FILTER,
        "photo":          ft.Icons.CAMERA_ALT,
        "dance":          ft.Icons.SELF_IMPROVEMENT,
        "travel":         ft.Icons.FLIGHT,
        "food":           ft.Icons.RESTAURANT,
        "fashion":        ft.Icons.STYLE,
        "coffee":         ft.Icons.LOCAL_CAFE,
        "hiking":         ft.Icons.TERRAIN,
        "rock_climbing":  ft.Icons.LANDSCAPE,
        "cycling":        ft.Icons.DIRECTIONS_BIKE,
        "running":        ft.Icons.DIRECTIONS_RUN,
        "gym":            ft.Icons.FITNESS_CENTER,
        "yoga":           ft.Icons.SPA,
        "swimming":       ft.Icons.POOL,
        "martial_arts":   ft.Icons.SPORTS_KABADDI,
        "badminton":      ft.Icons.SPORTS_TENNIS,
        "basketball":     ft.Icons.SPORTS_BASKETBALL,
        "volleyball":     ft.Icons.SPORTS_VOLLEYBALL,
        "table_tennis":   ft.Icons.SPORTS_TENNIS,
        "chess":          ft.Icons.GRID_ON,
        "handcraft":      ft.Icons.HANDYMAN,
        "plants":         ft.Icons.YARD,
        "pets":           ft.Icons.PETS,
    }

    def _chip_bgcolor(sel: bool):
        return (ft.Colors.with_opacity(0.75, ft.Colors.BLUE_400) if sel
                else ft.Colors.with_opacity(0.06, ft.Colors.WHITE))

    def _chip_border(sel: bool):
        return (ft.Border.all(1, ft.Colors.BLUE_400) if sel
                else ft.Border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE)))

    def _chip_color(sel: bool):
        return ft.Colors.WHITE if sel else ft.Colors.GREY_300

    def _make_chip(option_id: str, label: str) -> ft.Container:
        is_sel    = option_id in _selected_ids
        icon_name = _INTEREST_ICONS.get(option_id, ft.Icons.LABEL)

        icon_widget = ft.Icon(icon_name, size=14, color=_chip_color(is_sel))
        label_text  = ft.Text(
            label,
            size=12,
            color=_chip_color(is_sel),
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            no_wrap=True,
            expand=True,
        )
        btn = ft.Container(
            expand=True,
            height=36,
            border_radius=6,
            bgcolor=_chip_bgcolor(is_sel),
            border=_chip_border(is_sel),
            padding=ft.Padding.symmetric(horizontal=8),
            content=ft.Row(
                [icon_widget, label_text],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        def on_click(e):
            sel = option_id in _selected_ids
            if sel:
                _selected_ids.discard(option_id)
                sel = False
            else:
                _selected_ids.add(option_id)
                sel = True
            btn.bgcolor       = _chip_bgcolor(sel)
            btn.border        = _chip_border(sel)
            icon_widget.color = _chip_color(sel)
            label_text.color  = _chip_color(sel)
            _update_save_btn()
            page.update()

        btn.on_click = on_click
        return btn

    # ---- interest chips — uniform grid ----
    interest_chips = [
        _make_chip(item["id"], item["label"])
        for item in options.get("interest", [])
    ]

    # Group chips into rows of exactly _CHIPS_PER_ROW (last row may be shorter)
    _chip_rows = [
        ft.Row(
            interest_chips[i : i + _CHIPS_PER_ROW],
            spacing=_CHIP_SPACING,
        )
        for i in range(0, len(interest_chips), _CHIPS_PER_ROW)
    ]
    interest_grid = ft.Column(_chip_rows, spacing=_CHIP_SPACING)

    interest_header_row = ft.Row(
        [
            ft.Text("Interests & Hobbies", size=18, weight=ft.FontWeight.BOLD,
                    color=ft.Colors.GREY_200),
            ft.TextButton(
                content=ft.Row(
                    [ft.Icon(ft.Icons.ADD, size=14, color=ft.Colors.BLUE_300),
                     ft.Text("Add Custom", size=12, color=ft.Colors.BLUE_300)],
                    spacing=4,
                    tight=True,
                ),
                on_click=lambda e: None,   # TODO: Step 5 — AI keyword generation
                style=ft.ButtonStyle(
                    overlay_color={"": ft.Colors.TRANSPARENT},
                    padding=ft.Padding.all(0),
                ),
            ),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # ---- save handler ----
    def _on_save(e):
        save_selected_interests(list(_selected_ids))
        _saved_interests[0] = set(_selected_ids)
        _update_save_btn()
        page.snack_bar = ft.SnackBar(
            content=ft.Text("Preferences saved!", color=ft.Colors.WHITE),
            duration=2000,
        )
        page.snack_bar.open = True
        page.update()

    _save_btn.on_click = _on_save

    # ---- layout ----
    content = ft.Container(
        expand=True,
        padding=ft.Padding.only(top=16),
        content=ft.Column(
            [
                interest_grid,
                ft.Container(expand=True),
                ft.Row([_save_btn], alignment=ft.MainAxisAlignment.END),
            ],
            expand=True,
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    return SimpleNamespace(content=content)
