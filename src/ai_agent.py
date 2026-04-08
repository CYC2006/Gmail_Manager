import json
import os
import time
from google import genai
from dotenv import load_dotenv

# Load hidden variables in .env
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(dotenv_path=ENV_PATH)


# Get Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("API Key not Found")

client = genai.Client(api_key=GEMINI_API_KEY)


# Load Prompts into memory, avoid repeatedly read the hard drive
PROMPTS = {}
for p_file in ['moodle_analyzer1.txt', 'email_analyzer2.txt']:
    p_path = os.path.join(os.path.dirname(__file__), 'prompts', p_file)
    with open(p_path, 'r', encoding='utf-8') as file:
        PROMPTS[p_file] = file.read()


# Record last api call time
LAST_API_CALL_TIME = 0.0


# Analyze Email Content by Predefined Prompt
def analyze_email_content(clean_text, sender, receive_time, is_moodle=False):
    global LAST_API_CALL_TIME
    
    # Determine which template to use, directly get prompts from memory
    text_to_analyze = clean_text[:2000] 
    prompt_file = 'moodle_analyzer1.txt' if is_moodle else 'email_analyzer2.txt'
    prompt_template = PROMPTS[prompt_file]

    safe_sender = json.dumps(sender)[1:-1]
    safe_time = json.dumps(receive_time)[1:-1]
    safe_text = json.dumps(text_to_analyze)[1:-1]
        
    prompt = prompt_template.replace("{sender}", safe_sender).replace("{receive_time}", safe_time).replace("{text_to_analyze}", safe_text)
    

    # Proactive Pacing: to avoid 429 Error
    current_time = time.time()
    time_since_last_call = current_time - LAST_API_CALL_TIME
    if time_since_last_call < 6.5:
        time.sleep(6.5 - time_since_last_call)
    max_retries = 4
    base_wait = 10

    for attempt in range(max_retries):
        try:
            # 全速發送請求，不刻意 sleep
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )

            LAST_API_CALL_TIME = time.time()
            
            clean_response = response.text.strip()
            if clean_response.startswith("```json"):
                clean_response = clean_response.strip("`").removeprefix("json").strip()
                
            result_dict = json.loads(clean_response)
            return result_dict  # 成功就直接回傳，結束迴圈
            
        except Exception as e:
            error_msg = str(e)
            print(f"\n[DEBUG] API 錯誤細節: {error_msg}\n")

            if '429' in error_msg or 'RESOURCE_EXHAUSTED' in error_msg:
                # wait time: 10s -> 20s -> 40s -> 80s
                wait_time = base_wait * (2 ** attempt)
                print(f"🚦 觸發 API 頻率限制 (429)！等待 {wait_time} 秒後重試 (第 {attempt + 1}/{max_retries} 次)...")
                time.sleep(wait_time)
            else:
                print(f"❌ AI 分析失敗: {e}")
                break
                
    # if still failed to analyze
    return {
        "sender": sender,
        "time": receive_time,
        "category": "⚠️ Analysis Failed",
        "summary": "AI Analysis failed, please read manually.",
        "event_time": None,
        "action_required": None
    }