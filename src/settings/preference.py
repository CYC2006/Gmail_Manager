"""
preference.py
Builds the Preference settings tab.

Usage:
    from src.settings.preference import build_preference_tab

    _pref_tab = build_preference_tab(page)
    tab_content = _pref_tab.content
"""

import json
import os
from types import SimpleNamespace

import flet as ft

from src.config_manager import (
    get_selected_major,
    save_selected_major,
    get_selected_interests,
    save_selected_interests,
)

_OPTIONS_FILE = os.path.join(os.path.dirname(__file__), "preference_options.json")


def _load_options() -> dict:
    with open(_OPTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_preference_tab(page: ft.Page) -> SimpleNamespace:
    options = _load_options()

    # ---- state ----
    _selected_major:   list[str] = [get_selected_major()]      # single id
    _selected_ids:     set[str]  = set(get_selected_interests())
    _saved_major:      list[str] = [_selected_major[0]]
    _saved_interests:  list[set] = [set(_selected_ids)]

    # ---- save button (declared early so helpers can reference it) ----
    _save_btn = ft.ElevatedButton(
        "儲存",
        icon=ft.Icons.SAVE,
        disabled=True,
        style=ft.ButtonStyle(
            bgcolor={"": ft.Colors.GREY_800},
            color={"": ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        ),
    )

    # ---- helpers ----

    def _update_save_btn():
        major_changed    = _selected_major[0] != _saved_major[0]
        interest_changed = _selected_ids      != _saved_interests[0]
        changed = major_changed or interest_changed
        _save_btn.disabled = not changed
        _save_btn.style = ft.ButtonStyle(
            bgcolor={"": ft.Colors.BLUE_700 if changed else ft.Colors.GREY_800},
            color={"": ft.Colors.WHITE   if changed else ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        page.update()

    def _make_chip(option_id: str, label: str) -> ft.Chip:
        def on_select(e):
            if e.control.selected:
                _selected_ids.add(option_id)
            else:
                _selected_ids.discard(option_id)
            _update_save_btn()

        return ft.Chip(
            label=ft.Text(label, size=12, color=ft.Colors.GREY_200),
            selected=option_id in _selected_ids,
            on_select=on_select,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
            selected_color=ft.Colors.with_opacity(0.75, ft.Colors.BLUE_400),
            show_checkmark=False,
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        )

    # ---- major dropdown ----
    _major_dropdown = ft.Dropdown(
        value=_selected_major[0] or None,
        hint_text="Select your Major...",
        options=[
            ft.dropdown.Option(
                key=d["id"],
                text=f"{d['label']}（{d['abbr']}）",
            )
            for d in options["major"]
        ],
        bgcolor="#2a2a2a",
        border_color=ft.Colors.GREY_700,
        focused_border_color=ft.Colors.BLUE_400,
        color=ft.Colors.WHITE,
        menu_height=320,
    )

    def _on_major_select(e):
        _selected_major[0] = e.control.value or ""
        _update_save_btn()

    _major_dropdown.on_select = _on_major_select

    # ---- interest chips ----
    interest_chips = [
        _make_chip(item["id"], item["label"])
        for item in options["interest"]
    ]

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
        save_selected_major(_selected_major[0])
        save_selected_interests(list(_selected_ids))
        _saved_major[0]     = _selected_major[0]
        _saved_interests[0] = set(_selected_ids)
        _update_save_btn()
        page.snack_bar = ft.SnackBar(
            content=ft.Text("偏好設定已儲存！", color=ft.Colors.WHITE),
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
                ft.Text("Major", size=18, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREY_200),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                _major_dropdown,
                ft.Container(height=12),
                interest_header_row,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Row(interest_chips, wrap=True, spacing=6, run_spacing=6),
                ft.Container(expand=True),
                ft.Row([_save_btn], alignment=ft.MainAxisAlignment.END),
            ],
            expand=True,
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    return SimpleNamespace(content=content)
