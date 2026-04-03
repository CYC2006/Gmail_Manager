def mark_as_read(service, email_id):
    try:
        service.users().messages().modify(
            userId='me', 
            id=email_id, 
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        print(f"✅ 信件 {email_id} 已標示為已讀")
    except Exception as e:
        print(f"❌ 標示已讀失敗: {e}")

def toggle_star(service, email_id, add_star=True):
    try:
        body = {'addLabelIds': ['STARRED']} if add_star else {'removeLabelIds': ['STARRED']}
        service.users().messages().modify(userId='me', id=email_id, body=body).execute()
        print(f"⭐ 信件 {email_id} 星號狀態已更新")
    except Exception as e:
        print(f"❌ 星號更新失敗: {e}")

def archive_email(service, email_id):
    try:
        service.users().messages().modify(
            userId='me', 
            id=email_id, 
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        print(f"📦 信件 {email_id} 已封存 (移出收件匣)")
    except Exception as e:
        print(f"❌ 封存失敗: {e}")

def trash_email(service, email_id):
    try:
        # 刪除有自己專屬的 API endpoint
        service.users().messages().trash(userId='me', id=email_id).execute()
        print(f"🗑️ 信件 {email_id} 已移至垃圾桶 (30天後永久刪除)")
    except Exception as e:
        print(f"❌ 刪除失敗: {e}")