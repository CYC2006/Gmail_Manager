import flet as ft

def main(page: ft.Page):
    # ==========================
    # 1. Window Base Settings
    # ==========================
    page.title = "NCKU Gmail Manager"
    page.window.width = 1100
    page.window.height = 700
    page.window.resizable = False 
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    # ==========================
    # 2. UI Component Factory
    # ==========================
    def create_email_card(sender: str, time_str: str, category: str, summary: str, tag_color: str):
        return ft.Card(
            elevation=2,
            margin=10, 
            content=ft.Container(
                bgcolor="#2d2d2d", 
                padding=15,
                content=ft.Column([
                    ft.Row([
                        ft.Text(sender, weight=ft.FontWeight.BOLD, size=16, expand=True),
                        ft.Text(time_str, color=ft.Colors.OUTLINE, size=12)
                    ]),
                    ft.Row([
                        ft.Container(
                            content=ft.Text(category, size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                            bgcolor=tag_color,
                            padding=5, 
                            border_radius=5,
                        ),
                        ft.Text(summary, size=14, expand=True, color="#cccccc")
                    ]),
                    ft.Row([
                        # 🔧 全部修正為 ft.Icons 列舉
                        ft.IconButton(icon=ft.Icons.MARK_EMAIL_READ, tooltip="Mark as Read", icon_color=ft.Colors.BLUE_400),
                        ft.IconButton(icon=ft.Icons.STAR_BORDER, tooltip="Star", icon_color=ft.Colors.YELLOW_600),
                        ft.IconButton(icon=ft.Icons.ARCHIVE, tooltip="Archive", icon_color=ft.Colors.GREEN_400),
                        ft.IconButton(icon=ft.Icons.DELETE, tooltip="Trash", icon_color=ft.Colors.RED_400),
                    ], alignment=ft.MainAxisAlignment.END, spacing=0)
                ])
            )
        )

    # ==========================
    # 3. Sidebar (Left Navigation)
    # ==========================
    sidebar = ft.Container(
        width=250,
        bgcolor="#1e1e1e",
        padding=20,
        content=ft.Column([
            ft.Text("Cyc's Gmail Manager", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_200),
            ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
            
            # 🔧 全部修正為 ft.Icons 列舉
            ft.ListTile(leading=ft.Icon(ft.Icons.INBOX), title=ft.Text("Unread"), selected=True),
            ft.ListTile(leading=ft.Icon(ft.Icons.SCHOOL), title=ft.Text("Moodle")),
            ft.ListTile(leading=ft.Icon(ft.Icons.CAMPAIGN), title=ft.Text("Announcements")),
            
            ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
            
            ft.ListTile(leading=ft.Icon(ft.Icons.STAR), title=ft.Text("Starred")),
            ft.ListTile(leading=ft.Icon(ft.Icons.ARCHIVE), title=ft.Text("Archived")),
            ft.ListTile(leading=ft.Icon(ft.Icons.DELETE), title=ft.Text("Trash")),
        ])
    )

    # ==========================
    # 4. Main Content Area (Right)
    # ==========================
    main_content = ft.Container(
        expand=True,
        padding=30,
        bgcolor="#121212",
        content=ft.Column([
            ft.Row([
                ft.Text("Inbox - Unread Emails", size=28, weight=ft.FontWeight.BOLD),
                # 🔧 修正重新整理按鈕的 Icon
                ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Fetch New Emails", icon_color=ft.Colors.BLUE_200)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            
            ft.ListView(
                expand=True,
                spacing=5,
                controls=[
                    create_email_card("NCKU Library", "10:30 AM", "Important", "Library closing hours updated for the long weekend.", ft.Colors.RED_600),
                    create_email_card("Prof. Yu (Moodle)", "Yesterday", "Deadline", "CO PA1 submission due tonight at 23:59.", ft.Colors.ORANGE_600),
                    create_email_card("Student Union", "Apr 2", "Event", "Registration for the campus coding hackathon is now open.", ft.Colors.GREEN_600),
                    create_email_card("Dept. of Academic Affairs", "Apr 1", "General", "Course selection system maintenance scheduled.", ft.Colors.BLUE_600),
                    create_email_card("Prof. Lee (Moodle)", "Mar 30", "Grades", "Data Structures HW2 grades have been published.", ft.Colors.PURPLE_600),
                ]
            )
        ])
    )

    # ==========================
    # 5. Assemble the Layout
    # ==========================
    layout = ft.Row(
        expand=True,
        spacing=0,
        controls=[
            sidebar,
            ft.VerticalDivider(width=1, color=ft.Colors.OUTLINE_VARIANT),
            main_content
        ]
    )

    page.add(layout)

if __name__ == "__main__":
    ft.run(main)