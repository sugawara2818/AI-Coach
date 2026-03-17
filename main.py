import os
import random
import sqlite3
import psycopg2
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# --- CONFIG ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("POSTGRES_URL")

# --- INITIALIZATION ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    genai_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    genai_model = None

# --- DATABASE LOGIC ---
def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect("coach.db")
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            line_user_id TEXT PRIMARY KEY,
            name TEXT,
            goal TEXT,
            preferred_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
    else:
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            line_user_id TEXT PRIMARY KEY,
            name TEXT,
            goal TEXT,
            preferred_time TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
    conn.commit()
    cur.close()
    conn.close()

# --- COACHING LOGIC ---
def generate_ai_response(name, goal, user_message, proactive=False):
    if not genai_model:
        return "AI Coach is currently unavailable."
    
    if proactive:
        prompt = f"あなたはプロのコーチです。{name}さんの目標「{goal}」について、最近の状況を伺う短い応援メッセージを送ってください。"
    else:
        prompt = f"あなたはコーチです。{name}さんは「{goal}」という目標を持っています。彼らの発言「{user_message}」に対して、あたたかく、かつ前向きになれるコーチング的な返答をしてください。"
    
    try:
        response = genai_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AIエラー: {str(e)}"

# --- ENDPOINTS ---
@app.get("/", response_class=HTMLResponse)
async def home():
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Coach - 目標設定</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap" rel="stylesheet">
        <style>
            :root { --bg: #0a0a0c; --card: rgba(255, 255, 255, 0.05); --accent: #6c5ce7; --text: #ffffff; --text-dim: #a0a0a0; }
            body { margin: 0; font-family: 'Outfit', sans-serif; background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; }
            .container { background: var(--card); backdrop-filter: blur(20px); padding: 40px; border-radius: 24px; border: 1px solid rgba(255, 255, 255, 0.1); width: 90%; max-width: 400px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); }
            h1 { font-size: 32px; margin-bottom: 24px; text-align: center; background: linear-gradient(135deg, #fff 0%, #a0a0a0 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            .form-group { margin-bottom: 24px; }
            label { display: block; margin-bottom: 8px; font-size: 14px; color: var(--text-dim); }
            input, textarea { width: 100%; padding: 14px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.1); background: rgba(0, 0, 0, 0.3); color: #fff; font-size: 16px; transition: 0.3s; box-sizing: border-box; }
            input:focus, textarea:focus { outline: none; border-color: var(--accent); background: rgba(0, 0, 0, 0.5); }
            button { width: 100%; padding: 16px; border-radius: 12px; border: none; background: var(--accent); color: #fff; font-size: 16px; font-weight: 600; cursor: pointer; transition: 0.3s; margin-top: 10px; }
            button:hover { background: #5b4cc4; transform: translateY(-2px); }
            p.info { font-size: 12px; text-align: center; color: var(--text-dim); margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AI Coach</h1>
            <form id="goal-form">
                <div class="form-group"><label>LINE User ID</label><input type="text" id="line_user_id" placeholder="LINE Developersで見れるID" required></div>
                <div class="form-group"><label>お名前</label><input type="text" id="name" placeholder="コーチからの呼び名" required></div>
                <div class="form-group"><label>あなたの目標</label><textarea id="goal" rows="3" placeholder="例: 毎日10分読書する" required></textarea></div>
                <div class="form-group"><label>毎日状況を確認する時間</label><input type="time" id="preferred_time" required value="17:00"></div>
                <button type="submit">コーチングを開始する</button>
                <p class="info">※設定した時間に毎日メッセージが届きます</p>
            </form>
        </div>
        <script>
            document.getElementById('goal-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const data = {
                    line_user_id: document.getElementById('line_user_id').value,
                    name: document.getElementById('name').value,
                    goal: document.getElementById('goal').value,
                    preferred_time: document.getElementById('preferred_time').value
                };
                try {
                    const res = await fetch('/set_goal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
                    if (res.ok) alert('コーチング設定が完了しました！ LINEを確認してください。');
                    else alert('エラーが発生しました。設定を確認してください。');
                } catch (err) {
                    alert('通信エラーが発生しました。');
                }
            });
        </script>
    </body>
    </html>
    """
    return html_content

@app.post("/webhook")
async def webhook(request: Request):
    if not handler: return "LINE Handler not configured"
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    if not line_bot_api: return
    u_id = event.source.user_id
    text = event.message.text
    
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT name, goal FROM users WHERE line_user_id = %s", (u_id,))
    else:
        cur.execute("SELECT name, goal FROM users WHERE line_user_id = ?", (u_id,))
    user = cur.fetchone()
    
    if not user:
        reply = "目標が設定されていません。ウェブサイトから設定してください。"
    else:
        name, goal = (user[0], user[1]) if not isinstance(user, dict) else (user['name'], user['goal'])
        reply = generate_ai_response(name, goal, text)
    
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    cur.close()
    conn.close()

@app.post("/set_goal")
async def set_goal(data: dict):
    u_id, name, goal, p_time = data.get("line_user_id"), data.get("name"), data.get("goal"), data.get("preferred_time")
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("INSERT INTO users (line_user_id, name, goal, preferred_time) VALUES (%s, %s, %s, %s) ON CONFLICT (line_user_id) DO UPDATE SET name=EXCLUDED.name, goal=EXCLUDED.goal, preferred_time=EXCLUDED.preferred_time", (u_id, name, goal, p_time))
    else:
        cur.execute("INSERT OR REPLACE INTO users (line_user_id, name, goal, preferred_time) VALUES (?, ?, ?, ?)", (u_id, name, goal, p_time))
    conn.commit()
    cur.close()
    conn.close()
    if line_bot_api:
        line_bot_api.push_message(u_id, TextSendMessage(text=f"目標「{goal}」を設定しました！これからコーチとしてサポートします！"))
    return {"status": "success"}

@app.get("/api/cron")
async def cron_handler():
    conn = get_db_connection()
    cur = conn.cursor()
    # UTCからJST（+9時間）を考慮。Vercelの時間はUTC。
    now_jst = datetime.now() + timedelta(hours=9)
    now_time_str = now_jst.strftime("%H:%M")
    
    if DATABASE_URL:
        cur.execute("SELECT line_user_id, name, goal FROM users WHERE preferred_time = %s", (now_time_str,))
    else:
        cur.execute("SELECT line_user_id, name, goal FROM users WHERE preferred_time = ?", (now_time_str,))
    
    users = cur.fetchall()
    for user in users:
        u_id, name, goal = (user[0], user[1], user[2]) if not isinstance(user, dict) else (user['line_user_id'], user['name'], user['goal'])
        msg = generate_ai_response(name, goal, "", proactive=True)
        if line_bot_api:
            line_bot_api.push_message(u_id, TextSendMessage(text=msg))
    
    cur.close()
    conn.close()
    return {"status": "cron_finished"}

@app.get("/api/setup_db")
async def setup_db():
    init_db()
    return {"status": "connected_and_initialized"}
