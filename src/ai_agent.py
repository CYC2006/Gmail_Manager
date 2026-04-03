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

def analyze_email_content(clean_text, sender, receive_time, is_moodle=False):
    """
    讀取外部 Prompt 並將信件內文交給 Gemini 進行分析與資訊萃取
    """
    text_to_analyze = clean_text[:2000] 
    
    # [Prompt Routing] Determine which template to use
    prompt_file = 'moodle_analyzer1.txt' if is_moodle else 'email_analyzer1.txt'
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', prompt_file)
    
    with open(prompt_path, 'r', encoding='utf-8') as file:
        prompt_template = file.read()

    safe_sender = json.dumps(sender)[1:-1]
    safe_time = json.dumps(receive_time)[1:-1]
    safe_text = json.dumps(text_to_analyze)[1:-1]
        
    prompt = prompt_template.replace("{sender}", safe_sender)
    prompt = prompt.replace("{receive_time}", safe_time)
    prompt = prompt.replace("{text_to_analyze}", safe_text)
    

    # 🌟 Retry 3 times
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 全速發送請求，不刻意 sleep
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            
            clean_response = response.text.strip()
            if clean_response.startswith("```json"):
                clean_response = clean_response[7:-3]
                
            result_dict = json.loads(clean_response)
            return result_dict  # 成功就直接回傳，結束迴圈
            
        except Exception as e:
            error_msg = str(e)
            # 如果捕捉到 429 頻率限制錯誤
            if '429' in error_msg or 'RESOURCE_EXHAUSTED' in error_msg:
                wait_time = 20  # 稍微等久一點確保跨過一分鐘的計算區間
                print(f"🚦 觸發 API 頻率限制 (429)！等待 {wait_time} 秒後重試 (第 {attempt + 1}/{max_retries} 次)...")
                time.sleep(wait_time)
            else:
                # 如果是其他錯誤 (例如 JSON 解析失敗)，就直接印出錯誤並中斷
                print(f"❌ AI 分析失敗: {e}")
                break
                
    # 如果嘗試 3 次都失敗，或是發生其他嚴重錯誤，回傳失敗格式
    return {
        "sender": sender,
        "time": receive_time,
        "category": "⚠️ Analysis Failed",
        "summary": "AI Analysis failed, please read manually.",
        "event_time": None,
        "action_required": None
    }