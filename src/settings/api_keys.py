"""
settings_api_keys.py
Builds the API Keys settings tab for the Settings panel.

Usage:
    from src.settings_api_keys import build_api_keys_tab

    _api_tab = build_api_keys_tab(page)
    # mount content
    tab_content = _api_tab.content
    # trigger auto-verify when user opens Settings
    await _api_tab.auto_verify()
    # call on window close to purge non-verified keys
    _api_tab.save_verified_on_close()
"""

import asyncio
import webbrowser
from types import SimpleNamespace

import flet as ft

from src.ai_agent import verify_api_key, reload_keys
from src.config_manager import get_groq_api_keys, save_groq_api_keys


# ---------------------------------------------------------------------------
# Badge helpers  (pure UI, no page reference needed)
# ---------------------------------------------------------------------------

_BADGE_STYLES = {
    "verified":   (ft.Icons.CHECK,         "#4caf50"),
    "invalid":    (ft.Icons.CLOSE,         "#f44336"),
    "unverified": (ft.Icons.QUESTION_MARK, "#ffc107"),
}
_CHECKING_COLOR = "#555555"


def _make_badge(status: str = "unverified") -> ft.Container:
    if status == "checking":
        return ft.Container(
            data="checking",
            content=ft.Container(),
            width=48, height=48,
            alignment=ft.Alignment(0, 0),
            border=ft.Border.all(1, _CHECKING_COLOR),
            border_radius=8,
        )
    icon, color = _BADGE_STYLES[status]
    return ft.Container(
        data=status,
        content=ft.Icon(icon, size=24, color=color),
        width=48, height=48,
        alignment=ft.Alignment(0, 0),
        border=ft.Border.all(1, color),
        border_radius=8,
    )


def _set_badge_status(badge: ft.Container, status: str):
    badge.data = status
    if status == "checking":
        badge.border  = ft.Border.all(1, _CHECKING_COLOR)
        badge.content = ft.Container()
    else:
        icon, color   = _BADGE_STYLES[status]
        badge.border  = ft.Border.all(1, color)
        badge.content = ft.Icon(icon, size=24, color=color)


def _badge_status_of(badge: ft.Container) -> str:
    return badge.data if badge.data in ("verified", "invalid", "unverified") else "unverified"


# ---------------------------------------------------------------------------
# Tab builder
# ---------------------------------------------------------------------------

def build_api_keys_tab(page: ft.Page) -> SimpleNamespace:
    """Build the full API Keys tab and return a namespace with:
      .content               — the ft.Container to mount in the settings panel
      .auto_verify           — async coroutine; call via page.run_task(...)
      .save_verified_on_close — sync; call on page.on_close
    """

    # ---- state ----
    _key_fields:  list[ft.TextField]  = []
    _key_badges:  list[ft.Container]  = []
    _keys_list   = ft.Column(spacing=10)
    _saved_state = [[]]   # mutable single-element list for closure mutation

    # ---- helpers ----

    def _make_key_field(index: int) -> ft.TextField:
        return ft.TextField(
            label=f"Key {index}",
            password=True,
            can_reveal_password=True,
            bgcolor="#2a2a2a",
            border_color=ft.Colors.GREY_700,
            focused_border_color=ft.Colors.BLUE_400,
            label_style=ft.TextStyle(color=ft.Colors.GREY_400),
            color=ft.Colors.WHITE,
            expand=True,
            on_change=lambda e: _update_save_btn(),
        )

    def _current_values() -> list[str]:
        return [f.value or "" for f in _key_fields]

    def _saveable_values() -> list[str]:
        return [v.strip() for v in _current_values() if v.strip()]

    def _update_save_btn():
        has_content = bool(_saveable_values())
        changed     = _current_values() != _saved_state[0]
        enabled     = has_content and changed
        _save_btn.disabled = not enabled
        _save_btn.style = ft.ButtonStyle(
            bgcolor={"": ft.Colors.BLUE_700 if enabled else ft.Colors.GREY_800},
            color={"": ft.Colors.WHITE if enabled else ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        page.update()

    def _rebuild_list():
        _keys_list.controls = [
            ft.Row([field, badge], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER)
            for field, badge in zip(_key_fields, _key_badges)
        ]
        _minus_btn.disabled = len(_key_fields) <= 1
        _plus_btn.disabled  = len(_key_fields) >= 5
        _update_save_btn()

    def _on_minus(e):
        if len(_key_fields) > 1:
            _key_fields.pop()
            _key_badges.pop()
            _rebuild_list()

    def _on_plus(e):
        if len(_key_fields) < 5:
            _key_fields.append(_make_key_field(len(_key_fields) + 1))
            _key_badges.append(_make_badge("unverified"))
            _rebuild_list()

    # ---- async verify flows ----

    async def auto_verify():
        """Silently verify all filled keys; updates badges but does NOT save."""
        for field, badge in zip(_key_fields, _key_badges):
            if (field.value or "").strip():
                _set_badge_status(badge, "checking")
        page.update()
        for field, badge in zip(_key_fields, _key_badges):
            val = (field.value or "").strip()
            if val:
                status = await asyncio.to_thread(verify_api_key, val)
                _set_badge_status(badge, status)
                page.update()

    async def _verify_all_and_save():
        """Verify each non-empty key, update badges, then persist only verified ones."""
        for field, badge in zip(_key_fields, _key_badges):
            if (field.value or "").strip():
                _set_badge_status(badge, "checking")
        page.update()
        for field, badge in zip(_key_fields, _key_badges):
            val = (field.value or "").strip()
            if val:
                status = await asyncio.to_thread(verify_api_key, val)
            else:
                status = "unverified"
            _set_badge_status(badge, status)
        page.update()

        verified_keys = [
            (f.value or "").strip()
            for f, b in zip(_key_fields, _key_badges)
            if _badge_status_of(b) == "verified" and (f.value or "").strip()
        ]
        save_groq_api_keys(verified_keys)
        reload_keys()
        _saved_state[0] = _current_values()
        _update_save_btn()
        page.snack_bar = ft.SnackBar(
            content=ft.Text("API Keys saved!", color=ft.Colors.WHITE),
            duration=2000,
        )
        page.snack_bar.open = True
        page.update()

    def _on_save(e):
        _save_btn.disabled = True
        _save_btn.style = ft.ButtonStyle(
            bgcolor={"": ft.Colors.GREY_800},
            color={"": ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
        page.update()
        page.run_task(_verify_all_and_save)

    def save_verified_on_close():
        """Purge non-verified keys from config on window close."""
        try:
            verified_keys = [
                (f.value or "").strip()
                for f, b in zip(_key_fields, _key_badges)
                if _badge_status_of(b) == "verified" and (f.value or "").strip()
            ]
            save_groq_api_keys(verified_keys)
        except Exception:
            pass

    # ---- buttons ----

    _minus_btn = ft.IconButton(
        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
        icon_color=ft.Colors.GREY_400,
        icon_size=20,
        tooltip="Remove last key",
        on_click=_on_minus,
        disabled=True,
    )
    _plus_btn = ft.IconButton(
        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
        icon_color=ft.Colors.GREY_400,
        icon_size=20,
        tooltip="Add a key",
        on_click=_on_plus,
    )
    _save_btn = ft.ElevatedButton(
        "Save",
        icon=ft.Icons.SAVE,
        on_click=_on_save,
        disabled=True,
        style=ft.ButtonStyle(
            bgcolor={"": ft.Colors.GREY_800},
            color={"": ft.Colors.GREY_600},
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=8),
        ),
    )

    # ---- seed from saved config ----

    _saved_keys = get_groq_api_keys() or [""]
    for i, val in enumerate(_saved_keys):
        field = _make_key_field(i + 1)
        field.value = val
        _key_fields.append(field)
        _key_badges.append(_make_badge("verified" if val.strip() else "unverified"))
    _saved_state[0] = _current_values()
    _keys_list.controls = [
        ft.Row([f, b], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        for f, b in zip(_key_fields, _key_badges)
    ]
    _minus_btn.disabled = len(_key_fields) <= 1
    _plus_btn.disabled  = len(_key_fields) >= 5

    # ---- layout ----

    content = ft.Container(
        expand=True,
        padding=ft.Padding.only(top=16),
        content=ft.Column(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Text(
                                            "Groq API Keys",
                                            size=20,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.GREY_300,
                                        ),
                                        ft.TextButton(
                                            content=ft.Text(
                                                "Get a key ↗",
                                                size=11,
                                                color=ft.Colors.BLUE_300,
                                            ),
                                            on_click=lambda e: webbrowser.open(
                                                "https://console.groq.com/keys"
                                            ),
                                            style=ft.ButtonStyle(
                                                padding=ft.Padding.only(left=20),
                                                overlay_color={"": ft.Colors.TRANSPARENT},
                                            ),
                                        ),
                                    ],
                                    spacing=0,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Row([_minus_btn, _plus_btn], spacing=0),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ],
                    spacing=4,
                ),
                _keys_list,
                ft.Container(expand=True),   # spacer
                ft.Row([_save_btn], alignment=ft.MainAxisAlignment.END),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.INFO_OUTLINE,
                                            size=14, color=ft.Colors.AMBER_400),
                                    ft.Text(
                                        "API Key Notice",
                                        size=13,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.AMBER_400,
                                    ),
                                ],
                                spacing=6,
                            ),
                            ft.Text(
                                "• Never share your API key or post it online — treat it like a password.\n"
                                "• Each key is tied to your Groq account and usage is billed against it.\n"
                                "• Groq API keys have an expiration date. If requests start failing,\n"
                                "  go to console.groq.com/keys, create a new key, and update it here.",
                                size=12,
                                color=ft.Colors.GREY_400,
                            ),
                        ],
                        spacing=6,
                    ),
                    bgcolor="#2a2200",
                    border_radius=8,
                    padding=ft.Padding.all(14),
                ),
            ],
            expand=True,
            spacing=12,
        ),
    )

    return SimpleNamespace(
        content=content,
        auto_verify=auto_verify,
        save_verified_on_close=save_verified_on_close,
    )
