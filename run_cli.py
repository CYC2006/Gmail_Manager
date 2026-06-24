import sys
import os

# Ensure the root directory is in the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import get_gmail_service, fetch_and_analyze_emails
from src.email_actions import mark_as_read, archive_email, trash_email, toggle_star

def print_menu():
    print("\n" + "="*45)
    print("🚀 Cyc's Gmail Manager CLI 🚀")
    print("="*45)
    print("[1] 📥 Fetch and analyze unread emails")
    print("[2] 📖 Read/Manage specific email (Requires ID)")
    print("[3] 🧹 Sync and clean database (Coming soon)")
    print("[0] 🚪 Exit program")
    print("="*45)

def main():
    print("Starting system, verifying authentication...")
    service = get_gmail_service()
    
    if not service:
        print("Failed to obtain Gmail authorization. Terminating program.")
        return

    while True:
        print_menu()
        choice = input("👉 Please select an action (0-3): ").strip()
        
        if choice == '1':
            print("\nFetching unread emails for you...")
            fetch_and_analyze_emails(service) 
            
        elif choice == '2':
            email_id = input("\nPlease enter the Email ID you want to manage: ").strip()
            if not email_id:
                print("Email ID cannot be empty.")
                continue
                
            print(f"\nWhat would you like to do with email [{email_id}]?")
            print("  [R] Mark as Read")
            print("  [A] Archive")
            print("  [D] Move to Trash")
            print("  [S] Toggle Star")
            
            action = input("Your choice: ").strip().upper()
            
            if action == 'R':
                mark_as_read(service, email_id)
            elif action == 'A':
                archive_email(service, email_id)
            elif action == 'D':
                trash_email(service, email_id)
            elif action == 'S':
                # Defaulting to adding a star for simplicity, can be expanded later
                toggle_star(service, email_id, add_star=True)
            else:
                print("Invalid selection.")
                
        elif choice == '3':
            print("\nSync cleaning feature is under development...")
            
        elif choice == '0':
            print("\n👋 Thank you for using Gmail Manager. Goodbye!")
            sys.exit(0)
            
        else:
            print("\n⚠️ Invalid input, please try again.")

if __name__ == "__main__":
    main()