import os
from google import genai
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

print("🔍 正在查詢這把 API Key 支援的 Flash 模型清單...\n")

try:
    models = client.models.list()
    
    print("✅ 你可以使用的 Flash 系列模型有：")
    for m in models:
        # 新版 SDK 的模型名稱直接存在 m.name 裡面
        if 'flash' in m.name.lower():
            print(f" - {m.name}")
            
except Exception as e:
    print(f"❌ 查詢失敗: {e}")