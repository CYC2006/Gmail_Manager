"""
preference.py
Builds the Preference settings tab — 20 IAB categories × 5 interest chips.
"""

import json
import os
from types import SimpleNamespace

import flet as ft

from src.config_manager import get_selected_interests, save_selected_interests

_OPTIONS_FILE = os.path.join(os.path.dirname(__file__), "preference_options.json")

_CAT_LABEL_WIDTH = 152   # fixed width for the left category column
_CHIP_HEIGHT      = 42
_CHIP_SPACING     = 5
_ROW_SPACING      = 6


def _load_options() -> dict:
    try:
        with open(_OPTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[PREF] Failed to load preference options: {e}")
        return {}


def _icon(name: str) -> str:
    return getattr(ft.Icons, name, ft.Icons.LABEL)


def build_preference_tab(page: ft.Page) -> SimpleNamespace:
    options = _load_options()
    categories = options.get("categories", [])

    # ---- state ----
    _selected_ids: set[str] = set(get_selected_interests())

    def _autosave():
        save_selected_interests(list(_selected_ids))

    # ---- chip appearance helpers ----
    def _chip_bgcolor(sel: bool):
        return (ft.Colors.with_opacity(0.75, ft.Colors.BLUE_400) if sel
                else ft.Colors.with_opacity(0.06, ft.Colors.WHITE))

    def _chip_border(sel: bool):
        return (ft.Border.all(1, ft.Colors.BLUE_400) if sel
                else ft.Border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE)))

    def _chip_color(sel: bool):
        return ft.Colors.WHITE if sel else ft.Colors.GREY_300

    # ---- single interest chip ----
    def _make_chip(interest: dict) -> ft.Container:
        iid   = interest["id"]
        label = interest["label"]
        is_sel = iid in _selected_ids

        icon_widget = ft.Icon(_icon(interest.get("icon", "LABEL")), size=16, color=_chip_color(is_sel))
        label_text  = ft.Text(
            label,
            size=14,
            color=_chip_color(is_sel),
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            no_wrap=True,
            expand=True,
        )
        chip = ft.Container(
            expand=True,
            height=_CHIP_HEIGHT,
            border_radius=6,
            bgcolor=_chip_bgcolor(is_sel),
            border=_chip_border(is_sel),
            padding=ft.Padding.symmetric(horizontal=10),
            content=ft.Row(
                [icon_widget, label_text],
                spacing=7,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        def on_click(e):
            sel = iid in _selected_ids
            sel = not sel
            if sel:
                _selected_ids.add(iid)
            else:
                _selected_ids.discard(iid)
            chip.bgcolor       = _chip_bgcolor(sel)
            chip.border        = _chip_border(sel)
            icon_widget.color  = _chip_color(sel)
            label_text.color   = _chip_color(sel)
            _autosave()
            page.update()

        chip.on_click = on_click
        return chip

    # ---- empty slot placeholder (keeps column widths equal) ----
    def _empty_slot() -> ft.Container:
        return ft.Container(expand=True, height=_CHIP_HEIGHT)

    # ---- one category row ----
    def _make_category_row(cat: dict) -> ft.Row:
        interests = cat.get("interests", [])
        chips = []
        for i in range(5):
            chips.append(_make_chip(interests[i]) if i < len(interests) else _empty_slot())

        label_col = ft.Container(
            width=_CAT_LABEL_WIDTH,
            content=ft.Row(
                [
                    ft.Icon(_icon(cat.get("icon", "LABEL")), size=18, color=ft.Colors.GREY_500),
                    ft.Column(
                        [
                            ft.Text(
                                cat["label"],
                                size=14,
                                weight=ft.FontWeight.W_600,
                                color=ft.Colors.GREY_200,
                                no_wrap=True,
                            ),
                            ft.Text(
                                cat["abbr"],
                                size=10,
                                color=ft.Colors.GREY_600,
                                no_wrap=True,
                            ),
                        ],
                        spacing=1,
                        tight=True,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        chip_row = ft.Row(chips, spacing=_CHIP_SPACING, expand=True)

        return ft.Row(
            [label_col, chip_row],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # ---- assemble all rows ----
    category_rows = [_make_category_row(cat) for cat in categories]
    interest_grid = ft.Column(category_rows, spacing=_ROW_SPACING)

    # ---- layout ----
    content = ft.Container(
        expand=True,
        padding=ft.Padding.only(top=16),
        content=ft.Column(
            [interest_grid],
            expand=True,
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    return SimpleNamespace(content=content)
