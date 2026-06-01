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
        
        if add_star: print(f"⭐ 信件 {email_id} 已加上星號狀態")
        else: print(f"⭐ 信件 {email_id} 已取消星號狀態")
        
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

def unarchive_email(service, email_id):
    """Move an archived email back to Inbox by adding the INBOX label."""
    try:
        service.users().messages().modify(
            userId='me',
            id=email_id,
            body={'addLabelIds': ['INBOX']},
        ).execute()
        print(f"📥 Email {email_id} moved back to Inbox")
    except Exception as e:
        print(f"❌ Unarchive failed: {e}")

def restore_email(service, email_id):
    """Restore an email from Trash back to Inbox."""
    try:
        service.users().messages().modify(
            userId='me',
            id=email_id,
            body={'addLabelIds': ['INBOX'], 'removeLabelIds': ['TRASH']},
        ).execute()
        print(f"↩️ Email {email_id} restored to Inbox")
    except Exception as e:
        print(f"❌ Restore failed: {e}")

def permanent_delete_email(service, email_id):
    """Permanently delete an email — cannot be undone."""
    try:
        service.users().messages().delete(userId='me', id=email_id).execute()
        print(f"🗑️ Email {email_id} permanently deleted")
    except Exception as e:
        print(f"❌ Permanent delete failed: {e}")