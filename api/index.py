import os
import sys

# エラー内容を捕捉して表示するためのラッパー
try:
    import random
    import sqlite3
    from datetime import datetime, timedelta
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    from linebot import LineBotApi, WebhookHandler
    from linebot.exceptions import InvalidSignatureError
    from linebot.models import MessageEvent, TextMessage, TextSendMessage
    import google.generativeai as genai
    from dotenv import load_dotenv

    # Postgresはインポートに失敗しやすいため、個別にトラップ
    try:
        import psycopg2
    except ImportError:
        psycopg2 = None

    load_dotenv()

    app = FastAPI()

    # --- CONFIG ---
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    DATABASE_URL = os.getenv("POSTGRES_URL")

    # 初期化
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
    handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
    else:
        model = None

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "db_type": "postgres" if DATABASE_URL else "sqlite",
            "line_api": "configured" if line_bot_api else "missing",
            "gemini_api": "configured" if model else "missing",
            "psycopg2": "installed" if psycopg2 else "missing"
        }

    @app.get("/")
    async def home():
        return HTMLResponse("<h1>AI Coach is Running</h1><p>Check /api/health for status.</p>")

    # 既存のロジック（簡略化して再実装）
    @app.get("/api/setup_db")
    async def setup_db():
        if not DATABASE_URL:
            return {"error": "POSTGRES_URL is not set"}
        conn = psycopg2.connect(DATABASE_URL)
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
        return {"status": "Postgres initialized"}

    # Webhookなどは最小限に
    @app.post("/webhook")
    async def webhook(request: Request):
        if not handler: return "Not Configured"
        signature = request.headers.get("X-Line-Signature")
        body = await request.body()
        try:
            handler.handle(body.decode("utf-8"), signature)
        except:
            return "Error"
        return "OK"

except Exception as e:
    # 起動時にエラーが出た場合、その内容をFastAPIとしてではなく、単純なエラー出力として定義する
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    app = FastAPI()
    @app.get("/{full_path:path}")
    async def catch_all(full_path: str):
        import traceback
        return PlainTextResponse(f"Initialization Error:\n{str(e)}\n\n{traceback.format_exc()}", status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
