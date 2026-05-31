"""
account.py
Builds the Account settings tab — currently shows the Major selector.
"""

import json
import os
from types import SimpleNamespace

import flet as ft

from src.config_manager import get_selected_major, save_selected_major

_OPTIONS_FILE = os.path.join(os.path.dirname(__file__), "preference_options.json")


def _load_options() -> dict:
    try:
        with open(_OPTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ACCOUNT] Failed to load options: {e}")
        return {}


def build_account_tab(page: ft.Page) -> SimpleNamespace:
    options = _load_options()

    # ---- state ----
    _selected_major: list[str] = [get_selected_major()]
    _saved_major:    list[str] = [_selected_major[0]]

    # ---- save button ----
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

    def _update_save_btn():
        changed = _selected_major[0] != _saved_major[0]
        _save_btn.disabled = not changed
        _save_btn.style = ft.ButtonStyle(
            bgcolor={"": ft.Colors.BLUE_700 if changed else ft.Colors.GREY_800},
            color={"": ft.Colors.WHITE   if changed else ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        page.update()

    # ---- major dropdown ----
    _major_dropdown = ft.Dropdown(
        value=_selected_major[0] or None,
        hint_text="Select your Major...",
        options=[
            ft.dropdown.Option(
                key=d["id"],
                text=f"{d['label']} ({d['abbr']})",
            )
            for d in options.get("major", [])
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

    # ---- save handler ----
    def _on_save(e):
        save_selected_major(_selected_major[0])
        _saved_major[0] = _selected_major[0]
        _update_save_btn()
        page.snack_bar = ft.SnackBar(
            content=ft.Text("Account saved!", color=ft.Colors.WHITE),
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
                ft.Container(expand=True),
                ft.Row([_save_btn], alignment=ft.MainAxisAlignment.END),
            ],
            expand=True,
            spacing=10,
        ),
    )

    return SimpleNamespace(content=content)
