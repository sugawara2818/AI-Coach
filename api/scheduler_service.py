import time
import random
from datetime import datetime, timedelta
from linebot import LineBotApi
from linebot.models import TextSendMessage
import os
from dotenv import load_dotenv
from coach_logic import CoachLogic
from database_manager import get_db_connection

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
coach = CoachLogic()

def send_daily_checkins():
    """Checks the database and sends daily status check-in messages."""
    print(f"[{datetime.now()}] Checking for daily check-in opportunities...")
    conn = get_db_connection()
    cur = conn.cursor()
    
    current_time_obj = datetime.now()
    current_hour_min = current_time_obj.strftime("%H:%M")
    
    # Ideally, we trigger this every hour and find users who want a check-in at this hour.
    # On Vercel Hobby, it runs once. So we find everyone whose preferred_time matches the current hour,
    # OR if it's the only run of the day, we might just send to everyone who hasn't been messaged today.
    
    if os.getenv("POSTGRES_URL"):
        cur.execute("SELECT * FROM users WHERE preferred_time = %s", (current_hour_min,))
    else:
        cur.execute("SELECT * FROM users WHERE preferred_time = ?", (current_hour_min,))
    
    # NOTE: In Hobby Plan (once a day), if this runs at 17:00, only users set to 17:00 will get it.
    # To be more flexible on Hobby Plan, we could just send to everyone once a day regardless of their setting,
    # but the prompt specifically asked for user-defined time.
    
    users = cur.fetchall()
    
    for user in users:
        # Standardize access
        try:
            u_id, name, goal = user['line_user_id'], user['name'], user['goal']
        except:
            u_id, name, goal = user[0], user[1], user[2]
            
        # Persona: Status Check-in ("伺う")
        prompt = f"今日はどうですか？目標の「{goal}」について、進捗や今の気持ちを教えてください。"
        message_text = coach.generate_response(name, goal, "進捗はどうですか？状況を伺いにきました。")
        
        try:
            line_bot_api.push_message(u_id, TextSendMessage(text=message_text))
            
            # Record in history
            if os.getenv("POSTGRES_URL"):
                cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (%s, %s, %s)", 
                           (u_id, "coach", f"[Daily Check-in] {message_text}"))
            else:
                cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (?, ?, ?)", 
                           (u_id, "coach", f"[Daily Check-in] {message_text}"))
            
            conn.commit()
            print(f"Sent daily check-in to {name}")
            
        except Exception as e:
            print(f"Failed to send message to {u_id}: {e}")
            
    cur.close()
    conn.close()

def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    # Check every minute locally to be precise with user times
    scheduler.add_job(send_daily_checkins, 'interval', minutes=1)
    scheduler.start()
    print("Local daily check-in scheduler started (checking every 1 minute).")

if __name__ == "__main__":
    send_daily_checkins()
