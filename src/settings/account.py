"""
account.py
Builds the Account settings tab — Name, Gender, Major, Gmail Account.

Layout: each field is a single horizontal row:
    [label (fixed width)] [input widget (expand)]
"""

import json
import os
from types import SimpleNamespace

import flet as ft

from src.config_manager import (
    get_selected_major, save_selected_major,
    get_user_name,     save_user_name,
    get_user_gender,   save_user_gender,
    get_gmail_account, save_gmail_account,
)

_OPTIONS_FILE   = os.path.join(os.path.dirname(__file__), "preference_options.json")
_LABEL_WIDTH    = 120
_GENDER_OPTIONS = [("男", "male"), ("女", "female"), ("不透露", "undisclosed")]


def _load_options() -> dict:
    try:
        with open(_OPTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ACCOUNT] Failed to load options: {e}")
        return {}


def _text_field(**kwargs) -> ft.TextField:
    """Return a styled TextField with common dark-theme defaults."""
    return ft.TextField(
        bgcolor="#2a2a2a",
        border_color=ft.Colors.GREY_700,
        focused_border_color=ft.Colors.BLUE_400,
        color=ft.Colors.WHITE,
        label_style=ft.TextStyle(color=ft.Colors.GREY_400),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        expand=True,
        **kwargs,
    )


def build_account_tab(page: ft.Page) -> SimpleNamespace:
    options = _load_options()

    # ── state ──────────────────────────────────────────────────────────────
    # Plain dicts are mutable so closures can update them without nonlocal.
    _saved = {
        "name":   get_user_name(),
        "gender": get_user_gender(),
        "major":  get_selected_major(),
        "gmail":  get_gmail_account(),
    }
    _cur = dict(_saved)

    # ── save button (declared early so helpers can reference it) ───────────
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
        changed = any(_cur[k] != _saved[k] for k in _cur)
        _save_btn.disabled = not changed
        _save_btn.style = ft.ButtonStyle(
            bgcolor={"": ft.Colors.BLUE_700 if changed else ft.Colors.GREY_800},
            color={"": ft.Colors.WHITE   if changed else ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        page.update()

    # ── Name ───────────────────────────────────────────────────────────────
    _name_field = _text_field(value=_cur["name"], hint_text="Enter your name...")

    def _on_name_change(e):
        _cur["name"] = e.control.value or ""
        _update_save_btn()

    _name_field.on_change = _on_name_change

    # ── Gender chips ────────────────────────────────────────────────────────
    _gender_row = ft.Row(spacing=8, expand=True)

    def _chip_bg(sel: bool):
        return (ft.Colors.with_opacity(0.75, ft.Colors.BLUE_400) if sel
                else ft.Colors.with_opacity(0.06, ft.Colors.WHITE))

    def _chip_border(sel: bool):
        return (ft.Border.all(1, ft.Colors.BLUE_400) if sel
                else ft.Border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.WHITE)))

    def _chip_color(sel: bool):
        return ft.Colors.WHITE if sel else ft.Colors.GREY_300

    def _make_gender_chip(label: str, value: str) -> ft.Container:
        sel  = (_cur["gender"] == value)
        chip = ft.Container(
            height=36,
            border_radius=6,
            bgcolor=_chip_bg(sel),
            border=_chip_border(sel),
            padding=ft.Padding.symmetric(horizontal=16, vertical=6),
            content=ft.Text(label, size=13, color=_chip_color(sel)),
        )

        def _on_click(e, v=value):
            _cur["gender"] = v
            _rebuild_gender()
            _update_save_btn()

        chip.on_click = _on_click
        return chip

    def _rebuild_gender():
        _gender_row.controls = [
            _make_gender_chip(lbl, val) for lbl, val in _GENDER_OPTIONS
        ]
        page.update()

    _rebuild_gender()   # initial render

    # ── Major dropdown ──────────────────────────────────────────────────────
    _major_dropdown = ft.Dropdown(
        value=_cur["major"] or None,
        hint_text="Select your Major...",
        options=[
            ft.dropdown.Option(key=d["id"], text=f"{d['label']} ({d['abbr']})")
            for d in options.get("major", [])
        ],
        bgcolor="#2a2a2a",
        border_color=ft.Colors.GREY_700,
        focused_border_color=ft.Colors.BLUE_400,
        color=ft.Colors.WHITE,
        menu_height=320,
        expand=True,
    )

    def _on_major_select(e):
        _cur["major"] = e.control.value or ""
        _update_save_btn()

    _major_dropdown.on_select = _on_major_select

    # ── Gmail Account ───────────────────────────────────────────────────────
    _gmail_field = _text_field(
        value=_cur["gmail"],
        hint_text="your.email@gmail.com",
        keyboard_type=ft.KeyboardType.EMAIL,
    )

    def _on_gmail_change(e):
        _cur["gmail"] = e.control.value.strip()
        _update_save_btn()

    _gmail_field.on_change = _on_gmail_change

    # ── save handler ────────────────────────────────────────────────────────
    def _on_save(e):
        save_user_name(_cur["name"])
        save_user_gender(_cur["gender"])
        save_selected_major(_cur["major"])
        save_gmail_account(_cur["gmail"])
        _saved.update(_cur)
        _update_save_btn()
        page.snack_bar = ft.SnackBar(
            content=ft.Text("Account saved!", color=ft.Colors.WHITE),
            duration=2000,
        )
        page.snack_bar.open = True
        page.update()

    _save_btn.on_click = _on_save

    # ── layout helpers ──────────────────────────────────────────────────────
    def _label(text: str) -> ft.Text:
        return ft.Text(
            text,
            width=_LABEL_WIDTH,
            size=14,
            color=ft.Colors.GREY_300,
            weight=ft.FontWeight.W_500,
        )

    def _field_row(label_text: str, widget: ft.Control) -> ft.Row:
        return ft.Row(
            [_label(label_text), widget],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # ── Gmail note (shown below the Gmail field) ────────────────────────────
    _gmail_note = ft.Container(
        padding=ft.Padding.only(left=_LABEL_WIDTH + 4),
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE, size=12, color=ft.Colors.GREY_600),
                ft.Text(
                    "Gmail connection initialisation will be tied to this address in a future update.",
                    size=11,
                    color=ft.Colors.GREY_600,
                    italic=True,
                ),
            ],
            spacing=4,
        ),
    )

    # ── full tab content ─────────────────────────────────────────────────────
    content = ft.Container(
        expand=True,
        padding=ft.Padding.only(top=16),
        content=ft.Column(
            [
                ft.Text("Profile", size=18, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREY_200),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                _field_row("Name",          _name_field),
                _field_row("Gender",        _gender_row),
                _field_row("Major",         _major_dropdown),
                _field_row("Gmail Account", _gmail_field),
                _gmail_note,
                ft.Container(expand=True),
                ft.Row([_save_btn], alignment=ft.MainAxisAlignment.END),
            ],
            expand=True,
            spacing=12,
        ),
    )

    return SimpleNamespace(content=content)
