import sys
import os

# Ensure the root directory is in the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.gmail_reader import main as run_gmail_manager

if __name__ == "__main__":
    print("Starting Gmail Manager...")
    run_gmail_manager()