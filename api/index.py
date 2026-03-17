import os
import sqlite3
import traceback
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

# Try to load .env for local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI()

# --- GLOBAL INSTANCES ---
_line_api = None
_line_handler = None
_gemini_model = None

def get_line_api():
    global _line_api
    if _line_api: return _line_api
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if token:
        _line_api = LineBotApi(token)
    return _line_api

def get_gemini_model():
    global _gemini_model
    if _gemini_model: return _gemini_model
    key = os.getenv("GEMINI_API_KEY")
    if key:
        genai.configure(api_key=key)
        # We will try to get a model instance later when needed, or check what exists
        # For now, we return the genai module or a placeholder helper
        return True 
    return None

def get_actual_model_with_error():
    # Try multiple common model names in order of reliability
    models_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-flash-latest',
        'gemini-1.5-pro',
        'gemini-2.0-flash'
    ]
    
    errors = []
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            # Try a very small generation to verify quota/existence
            model.generate_content("ping", generation_config={"max_output_tokens": 1})
            return model, None
        except Exception as e:
            errors.append(f"{model_name}: {str(e)}")
            continue
    return None, " | ".join(errors)

def get_db_connection():
    url = os.getenv("POSTGRES_URL")
    if url:
        try:
            import psycopg2
            return psycopg2.connect(url)
        except Exception as e:
            print(f"Postgres connection error: {e}")
            raise e
    else:
        if os.getenv("VERCEL"):
            raise Exception("Vercel Postgres (POSTGRES_URL) is not configured.")
        conn = sqlite3.connect("coach.db")
        conn.row_factory = sqlite3.Row
        return conn

# --- COACHING LOGIC ---
def generate_ai_response(name, goal, user_message, proactive=False):
    model, error_details = get_actual_model_with_error()
    if not model:
        return f"AIコーチは現在準備中です（利用可能なAIモデルが見つかりません）。\nエラー詳細: {error_details}"
    
    if proactive:
        prompt = f"あなたは{name}さんの専属コーチです。{name}さんは「{goal}」という目標を持っています。最近の状況を伺い、励ますような短いメッセージを送ってください。"
    else:
        prompt = f"あなたは{name}さんのコーチです。目標は「{goal}」です。発言「{user_message}」に対して、コーチングの視点から前向きな返答をしてください。"
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AIエラーが発生しました: {str(e)}"

# --- LINE HANDLER REGISTRATION ---
def get_line_handler():
    global _line_handler
    if _line_handler: return _line_handler
    
    secret = os.getenv("LINE_CHANNEL_SECRET")
    if not secret: return None
    
    _line_handler = WebhookHandler(secret)
    
    @_line_handler.add(MessageEvent, message=TextMessage)
    def handle_line_message(event):
        line_api = get_line_api()
        if not line_api: return
        
        u_id = event.source.user_id
        text = event.message.text.strip()
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        if os.getenv("POSTGRES_URL"):
            cur.execute("SELECT name, goal, preferred_time, onboarding_step FROM users WHERE line_user_id = %s", (u_id,))
        else:
            cur.execute("SELECT name, goal, preferred_time, onboarding_step FROM users WHERE line_user_id = ?", (u_id,))
        user = cur.fetchone()
        
        u_name, u_goal, u_time, u_step = None, None, None, 0
        if user:
            try:
                u_name, u_goal, u_time, u_step = (user[0], user[1], user[2], user[3]) if not hasattr(user, 'keys') else (user['name'], user['goal'], user['preferred_time'], user['onboarding_step'])
            except:
                u_name, u_goal, u_time = (user[0], user[1], user[2]) if not hasattr(user, 'keys') else (user['name'], user['goal'], user['preferred_time'])
                u_step = 4
        
        reply = ""
        if u_step < 4:
            if u_step == 0:
                if os.getenv("POSTGRES_URL"):
                    cur.execute("INSERT INTO users (line_user_id, onboarding_step) VALUES (%s, 1) ON CONFLICT (line_user_id) DO UPDATE SET onboarding_step = 1", (u_id,))
                else:
                    cur.execute("INSERT OR REPLACE INTO users (line_user_id, onboarding_step) VALUES (?, 1)", (u_id,))
                reply = "はじめまして！あなたの目標達成を全力でサポートするAIコーチです。\n\nまずは、あなたの[お名前]を教えてください。"
            elif u_step == 1:
                if os.getenv("POSTGRES_URL"):
                    cur.execute("UPDATE users SET name = %s, onboarding_step = 2 WHERE line_user_id = %s", (text, u_id))
                else:
                    cur.execute("UPDATE users SET name = ?, onboarding_step = 2 WHERE line_user_id = ?", (text, u_id))
                reply = f"ありがとうございます、{text}さん！次に、あなたが達成したい[具体的な目標]を教えてください。"
            elif u_step == 2:
                if os.getenv("POSTGRES_URL"):
                    cur.execute("UPDATE users SET goal = %s, onboarding_step = 3 WHERE line_user_id = %s", (text, u_id))
                else:
                    cur.execute("UPDATE users SET goal = ?, onboarding_step = 3 WHERE line_user_id = ?", (text, u_id))
                reply = "素晴らしい目標ですね！最後に、毎日何時に状況を確認してほしいですか？[17:00]のように教えてください。"
            elif u_step == 3:
                if ":" in text and len(text) <= 5:
                    if os.getenv("POSTGRES_URL"):
                        cur.execute("UPDATE users SET preferred_time = %s, onboarding_step = 4 WHERE line_user_id = %s", (text, u_id))
                    else:
                        cur.execute("UPDATE users SET preferred_time = ?, onboarding_step = 4 WHERE line_user_id = ?", (text, u_id))
                    reply = f"設定完了です！これから毎日 {text} に伺います。今日からよろしくお願いします！"
                else:
                    reply = "時間の形式が正しくないようです。[17:00]のように教えていただけますか？"
            conn.commit()
        else:
            if not u_name or not u_goal:
                reply = "目標が設定されていません。ウェブサイトから設定してください。"
            else:
                reply = generate_ai_response(u_name, u_goal, text)
        
        line_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        cur.close()
        conn.close()

    return _line_handler

# --- ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head><meta charset="UTF-8"><title>AI Coach</title></head>
    <body style="background:#000;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;">
        <div style="background:#111;padding:2rem;border-radius:1rem;width:300px;">
            <h1>AI Coach</h1>
            <p>LINE公式アカウントから「こんにちは」と送って設定を開始してください。</p>
        </div>
    </body>
    </html>
    """

@app.get("/api/models")
async def list_models_endpoint():
    key = os.getenv("GEMINI_API_KEY")
    if not key: return {"error": "API key not set"}
    try:
        genai.configure(api_key=key)
        models = []
        for m in genai.list_models():
            models.append({
                "name": m.name,
                "display_name": m.display_name,
                "supported_methods": m.supported_generation_methods
            })
        return {"available_models": models}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/health")
async def health():
    return {"status": "ok", "line_configured": get_line_handler() is not None}

@app.post("/webhook")
async def webhook(request: Request):
    handler = get_line_handler()
    if not handler: return "Handler not configured"
    
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400)
    except Exception as e:
        return PlainTextResponse(str(e), status_code=500)
    return "OK"

@app.post("/set_goal")
async def set_goal(data: dict):
    u_id, name, goal, p_time = data.get("line_user_id"), data.get("name"), data.get("goal"), data.get("preferred_time")
    conn = get_db_connection()
    cur = conn.cursor()
    if os.getenv("POSTGRES_URL"):
        cur.execute("INSERT INTO users (line_user_id, name, goal, preferred_time, onboarding_step) VALUES (%s, %s, %s, %s, 4) ON CONFLICT (line_user_id) DO UPDATE SET name=EXCLUDED.name, goal=EXCLUDED.goal, preferred_time=EXCLUDED.preferred_time, onboarding_step=4", (u_id, name, goal, p_time))
    else:
        cur.execute("INSERT OR REPLACE INTO users (line_user_id, name, goal, preferred_time, onboarding_step) VALUES (?, ?, ?, ?, 4)", (u_id, name, goal, p_time))
    conn.commit()
    cur.close()
    conn.close()
    
    line_api = get_line_api()
    if line_api:
        line_api.push_message(u_id, TextSendMessage(text=f"目標「{goal}」を設定しました！"))
    return {"status": "success"}

@app.get("/api/cron")
async def cron():
    conn = get_db_connection()
    cur = conn.cursor()
    now_jst = datetime.utcnow() + timedelta(hours=9)
    time_str = now_jst.strftime("%H:%M")
    
    if os.getenv("POSTGRES_URL"):
        cur.execute("SELECT line_user_id, name, goal FROM users WHERE preferred_time = %s AND onboarding_step = 4", (time_str,))
    else:
        cur.execute("SELECT line_user_id, name, goal FROM users WHERE preferred_time = ? AND onboarding_step = 4", (time_str,))
    
    users = cur.fetchall()
    line_api = get_line_api()
    for user in users:
        try:
            u_id, name, goal = (user[0], user[1], user[2]) if not hasattr(user, 'keys') else (user['line_user_id'], user['name'], user['goal'])
            msg = generate_ai_response(name, goal, "", proactive=True)
            if line_api: line_api.push_message(u_id, TextSendMessage(text=msg))
        except: pass
            
    cur.close()
    conn.close()
    return {"status": "cron completed"}

@app.get("/api/setup_db")
async def setup_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if os.getenv("POSTGRES_URL"):
            cur.execute("CREATE TABLE IF NOT EXISTS users (line_user_id TEXT PRIMARY KEY, name TEXT, goal TEXT, preferred_time TEXT, onboarding_step INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        else:
            cur.execute("CREATE TABLE IF NOT EXISTS users (line_user_id TEXT PRIMARY KEY, name TEXT, goal TEXT, preferred_time TEXT, onboarding_step INTEGER DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "initialized"}
    except Exception as e:
        return PlainTextResponse(traceback.format_exc(), status_code=500)
