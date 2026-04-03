import json
import os
import time  # 引入時間模組來處理延遲
from google import genai
from dotenv import load_dotenv

# 載入 .env 檔案中的隱藏變數
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("找不到 API Key！請檢查根目錄是否有 .env 檔案。")

client = genai.Client(api_key=GEMINI_API_KEY)

def analyze_email_content(clean_text, sender, receive_time):
    """
    讀取外部 Prompt 並將信件內文交給 Gemini 進行分析與資訊萃取
    """
    text_to_analyze = clean_text[:2000] 
    
    # [修復魔王一]：使用 json.dumps() 自動處理字串跳脫，避免破壞 JSON 結構
    safe_sender = json.dumps(sender)[1:-1]
    safe_time = json.dumps(receive_time)[1:-1]
    # 我們也順便把內文跳脫一下，避免信件內文裡有引號干擾 JSON
    safe_text = json.dumps(text_to_analyze)[1:-1]
    
    # 讀取 prompt 模板
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'email_analyzer1.txt')
    with open(prompt_path, 'r', encoding='utf-8') as file:
        prompt_template = file.read()
        
    prompt = prompt_template.replace("{sender}", safe_sender)
    prompt = prompt.replace("{receive_time}", safe_time)
    prompt = prompt.replace("{text_to_analyze}", safe_text)
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        # [修復魔王二]：成功取得結果後，強制程式休息 15 秒，避免觸發 429 限制 (5 RPM)
        # 因為免費版一分鐘 5 次，平均 12 秒一次。我們設定 15 秒比較安全。
        print("⏳ 避免觸發 API 頻率限制，休息 15 秒...")
        time.sleep(15) 
        
        # 移除可能出現的 Markdown 標記，確保是純 JSON
        clean_response = response.text.strip()
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:-3]
            
        result_dict = json.loads(clean_response)
        return result_dict
        
    except Exception as e:
        print(f"AI Analysis failed: {e}")
        return {
            "sender": sender,
            "time": receive_time,
            "category": "⚠️ Analysis Failed",
            "summary": "AI Analysis failed, please read manually.",
            "event_time": None,
            "action_required": None
        }