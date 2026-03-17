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

# Vercel env vars are native, but we can try to load .env for local dev
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI()

# --- LAZY INITIALIZERS ---
# We initialize these inside the functions to prevent the function from crashing during the import phase
# if environment variables are missing.

def get_line_api():
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        return None
    try:
        return LineBotApi(token)
    except Exception as e:
        print(f"LineBotApi init error: {e}")
        return None

def get_line_handler():
    secret = os.getenv("LINE_CHANNEL_SECRET")
    if not secret:
        return None
    try:
        return WebhookHandler(secret)
    except Exception as e:
        print(f"WebhookHandler init error: {e}")
        return None

def get_gemini_model():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        genai.configure(api_key=key)
        return genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini init error: {e}")
        return None

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
        # Fallback to local SQLite for non-production environments
        conn = sqlite3.connect("coach.db")
        conn.row_factory = sqlite3.Row
        return conn

# --- CORE LOGIC ---

def generate_ai_response(name, goal, user_message, proactive=False):
    model = get_gemini_model()
    if not model:
        return "AIコーチは現在準備中です（APIキーが設定されていません）。"
    
    if proactive:
        prompt = f"あなたは{name}さんの専属コーチです。{name}さんは「{goal}」という目標を持っています。最近の状況を伺い、励ますような短いメッセージを送ってください。"
    else:
        prompt = f"あなたは{name}さんのコーチです。目標は「{goal}」です。発言「{user_message}」に対して、コーチングの視点から前向きな返答をしてください。"
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AIエラーが発生しました: {str(e)}"

# --- ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def home():
    # Embedding HTML directly to avoid file path issues
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Coach - 目標設定</title>
        <style>
            body { font-family: sans-serif; background: #0f0f12; color: #fff; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
            .card { background: #1a1a20; padding: 2rem; border-radius: 1rem; width: 90%; max-width: 400px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
            h1 { margin-top: 0; color: #6c5ce7; }
            .field { margin-bottom: 1.5rem; }
            label { display: block; margin-bottom: 0.5rem; color: #aaa; font-size: 0.9rem; }
            input, textarea { width: 100%; padding: 0.8rem; border-radius: 0.5rem; border: 1px solid #333; background: #000; color: #fff; box-sizing: border-box; }
            button { width: 100%; padding: 1rem; border-radius: 0.5rem; border: none; background: #6c5ce7; color: #fff; font-weight: bold; cursor: pointer; }
            button:hover { background: #5b4cc4; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>AI Coach</h1>
            <form id="form">
                <div class="field"><label>LINE User ID</label><input type="text" id="uid" required></div>
                <div class="field"><label>お名前</label><input type="text" id="name" required></div>
                <div class="field"><label>目標</label><textarea id="goal" rows="3" required></textarea></div>
                <div class="field"><label>確認時間</label><input type="time" id="time" value="17:00" required></div>
                <button type="submit">コーチング開始</button>
            </form>
        </div>
        <script>
            document.getElementById('form').onsubmit = async (e) => {
                e.preventDefault();
                const data = {
                    line_user_id: document.getElementById('uid').value,
                    name: document.getElementById('name').value,
                    goal: document.getElementById('goal').value,
                    preferred_time: document.getElementById('time').value
                };
                const res = await fetch('/set_goal', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) alert('設定しました！LINEをご確認ください。');
                else alert('エラーが発生しました。');
            };
        </script>
    </body>
    </html>
    """

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "env": {
            "LINE_TOKEN": "set" if os.getenv("LINE_CHANNEL_ACCESS_TOKEN") else "MISSING",
            "LINE_SECRET": "set" if os.getenv("LINE_CHANNEL_SECRET") else "MISSING",
            "GEMINI_KEY": "set" if os.getenv("GEMINI_API_KEY") else "MISSING",
            "POSTGRES": "set" if os.getenv("POSTGRES_URL") else "MISSING (SQLite Fallback)"
        }
    }

@app.post("/webhook")
async def webhook(request: Request):
    handler = get_line_handler()
    if not handler:
        return "Webhook handler not configured"
    
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400)
    except Exception as e:
        print(f"Webhook error: {e}")
        return PlainTextResponse(str(e), status_code=500)
    return "OK"

# Inlined handler to keep everything in one file
line_handler = get_line_handler()
if line_handler:
    @line_handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        u_id = event.source.user_id
        text = event.message.text
        
        conn = get_db_connection()
        cur = conn.cursor()
        if os.getenv("POSTGRES_URL"):
            cur.execute("SELECT name, goal FROM users WHERE line_user_id = %s", (u_id,))
        else:
            cur.execute("SELECT name, goal FROM users WHERE line_user_id = ?", (u_id,))
        user = cur.fetchone()
        
        if not user:
            reply = "目標が設定されていません。ウェブサイトから設定してください。"
        else:
            # Handle both dict-like and tuple-like row access
            try:
                name, goal = (user[0], user[1]) if not hasattr(user, 'keys') else (user['name'], user['goal'])
            except:
                name, goal = user[0], user[1]
            reply = generate_ai_response(name, goal, text)
        
        line_api = get_line_api()
        if line_api:
            line_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        cur.close()
        conn.close()

@app.post("/set_goal")
async def set_goal(data: dict):
    u_id = data.get("line_user_id")
    name = data.get("name")
    goal = data.get("goal")
    p_time = data.get("preferred_time")
    
    conn = get_db_connection()
    cur = conn.cursor()
    if os.getenv("POSTGRES_URL"):
        cur.execute("INSERT INTO users (line_user_id, name, goal, preferred_time) VALUES (%s, %s, %s, %s) ON CONFLICT (line_user_id) DO UPDATE SET name=EXCLUDED.name, goal=EXCLUDED.goal, preferred_time=EXCLUDED.preferred_time", (u_id, name, goal, p_time))
    else:
        cur.execute("INSERT OR REPLACE INTO users (line_user_id, name, goal, preferred_time) VALUES (?, ?, ?, ?)", (u_id, name, goal, p_time))
    conn.commit()
    cur.close()
    conn.close()
    
    line_api = get_line_api()
    if line_api:
        line_api.push_message(u_id, TextSendMessage(text=f"目標「{goal}」を設定しました！これからコーチとしてサポートします！"))
    
    return {"status": "success"}

@app.get("/api/cron")
async def cron():
    # Inlined cron logic
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Calculate JST
    now_jst = datetime.utcnow() + timedelta(hours=9)
    time_str = now_jst.strftime("%H:%M")
    
    if os.getenv("POSTGRES_URL"):
        cur.execute("SELECT line_user_id, name, goal FROM users WHERE preferred_time = %s", (time_str,))
    else:
        cur.execute("SELECT line_user_id, name, goal FROM users WHERE preferred_time = ?", (time_str,))
    
    users = cur.fetchall()
    line_api = get_line_api()
    
    for user in users:
        try:
            u_id, name, goal = (user[0], user[1], user[2]) if not hasattr(user, 'keys') else (user['line_user_id'], user['name'], user['goal'])
        except:
            u_id, name, goal = user[0], user[1], user[2]
            
        msg = generate_ai_response(name, goal, "", proactive=True)
        if line_api:
            line_api.push_message(u_id, TextSendMessage(text=msg))
            
    cur.close()
    conn.close()
    return {"status": "cron completed"}

@app.get("/api/setup_db")
async def setup_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                line_user_id TEXT PRIMARY KEY,
                name TEXT,
                goal TEXT,
                preferred_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "initialized"}
    except Exception as e:
        return PlainTextResponse(traceback.format_exc(), status_code=500)
