import os
import random
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from dotenv import load_dotenv
from coach_logic import CoachLogic
from database_manager import get_db_connection
from scheduler_service import send_proactive_messages, start_scheduler

load_dotenv()

app = FastAPI()

# Only start background scheduler if running locally (not on Vercel)
@app.on_event("startup")
async def startup_event():
    if not os.getenv("VERCEL"):
        start_scheduler()

# LINE credentials
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# Initialize safely to avoid crash if env vars are missing during build/first run
line_bot_api = None
handler = None
if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)

coach = CoachLogic()

@app.post("/webhook")
async def webhook(request: Request):
    if not handler:
        return "Webhook not configured"
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    line_user_id = event.source.user_id
    user_message = event.message.text
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Query logic depending on DB type
    if os.getenv("POSTGRES_URL"):
        cur.execute("SELECT * FROM users WHERE line_user_id = %s", (line_user_id,))
    else:
        cur.execute("SELECT * FROM users WHERE line_user_id = ?", (line_user_id,))
    
    user = cur.fetchone()
    
    if not user:
        reply_text = "こんにちは！コーチングを始める前に、まずは目標を設定しましょう。こちらのリンクからどうぞ：[あなたのサイトのURL]"
    else:
        # Standardize user data access
        if isinstance(user, dict):
            name, goal = user['name'], user['goal']
        else:
            try:
                name, goal = user['name'], user['goal']
            except:
                name, goal = user[1], user[2]
                
        response_text = coach.generate_response(name, goal, user_message)
        
        # Save to history
        if os.getenv("POSTGRES_URL"):
            cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (%s, %s, %s)", 
                       (line_user_id, "user", user_message))
            cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (%s, %s, %s)", 
                       (line_user_id, "coach", response_text))
        else:
            cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (?, ?, ?)", 
                       (line_user_id, "user", user_message))
            cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (?, ?, ?)", 
                       (line_user_id, "coach", response_text))
        conn.commit()
        reply_text = response_text
    
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    cur.close()
    conn.close()

@app.get("/", response_class=HTMLResponse)
async def home():
    # Fix pathing for Vercel
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "index.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/set_goal")
async def set_goal(data: dict):
    line_user_id = data.get("line_user_id")
    name = data.get("name")
    goal = data.get("goal")
    preferred_time = data.get("preferred_time", "17:00")
    
    if not line_user_id or not name or not goal:
        raise HTTPException(status_code=400, detail="Missing data")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if os.getenv("POSTGRES_URL"):
        cur.execute('''
            INSERT INTO users (line_user_id, name, goal, frequency, preferred_time) 
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (line_user_id) DO UPDATE SET name = EXCLUDED.name, goal = EXCLUDED.goal, preferred_time = EXCLUDED.preferred_time
        ''', (line_user_id, name, goal, "daily", preferred_time))
    else:
        cur.execute('''
            INSERT OR REPLACE INTO users (line_user_id, name, goal, frequency, preferred_time) 
            VALUES (?, ?, ?, ?, ?)
        ''', (line_user_id, name, goal, "daily", preferred_time))
        
    conn.commit()
    cur.close()
    conn.close()
    
    try:
        line_bot_api.push_message(line_user_id, TextSendMessage(text=f"目標設定完了しました！{name}さん、これからコーチとして全力でサポートしますね。"))
    except Exception as e:
        print(f"Error pushing message: {e}")
        
    return {"status": "success"}

# Vercel Cron endpoint
@app.get("/api/cron")
async def cron_handler():
    send_proactive_messages()
    return {"status": "cron execution completed"}

# Vercel DB Setup endpoint
@app.get("/api/setup_db")
async def setup_db_handler():
    from database_manager import init_db
    init_db()
    return {"status": "Postgres initialized"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
