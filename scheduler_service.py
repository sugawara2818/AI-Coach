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

def send_proactive_messages():
    """Checks the database and sends proactive messages to users at irregular intervals."""
    print(f"[{datetime.now()}] Checking for proactive message opportunities...")
    conn = get_db_connection()
    cur = conn.cursor()
    
    current_time = datetime.now()
    
    # Query logic depending on DB type
    if os.getenv("POSTGRES_URL"):
        cur.execute("SELECT * FROM users WHERE next_ping_at <= %s OR next_ping_at IS NULL", (current_time,))
    else:
        current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("SELECT * FROM users WHERE next_ping_at <= ? OR next_ping_at IS NULL", (current_time_str,))
    
    users = cur.fetchall()
    
    for user in users:
        # Compatibility between SQLite (Row) and Postgres (tuple/dict)
        if isinstance(user, dict):
            u_id, name, goal = user['line_user_id'], user['name'], user['goal']
        else:
            # Assuming RealDictCursor or Row-like access
            try:
                u_id, name, goal = user['line_user_id'], user['name'], user['goal']
            except:
                # Fallback for standard tuple
                u_id, name, goal = user[0], user[1], user[2]
        
        message_text = coach.generate_proactive_message(name, goal)
        
        try:
            line_bot_api.push_message(u_id, TextSendMessage(text=message_text))
            
            # Record in history
            if os.getenv("POSTGRES_URL"):
                cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (%s, %s, %s)", 
                           (u_id, "coach", f"[Proactive] {message_text}"))
            else:
                cur.execute("INSERT INTO chat_history (line_user_id, role, message) VALUES (?, ?, ?)", 
                           (u_id, "coach", f"[Proactive] {message_text}"))
            
            # Set next ping time randomly between 4 and 16 hours from now
            random_hours = random.randint(4, 16)
            next_ping = datetime.now() + timedelta(hours=random_hours)
            
            if os.getenv("POSTGRES_URL"):
                cur.execute("UPDATE users SET next_ping_at = %s WHERE line_user_id = %s", (next_ping, u_id))
            else:
                next_ping_str = next_ping.strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("UPDATE users SET next_ping_at = ? WHERE line_user_id = ?", (next_ping_str, u_id))
            
            conn.commit()
            print(f"Sent proactive message to {name}. Next ping: {next_ping}")
            
        except Exception as e:
            print(f"Failed to send message to {u_id}: {e}")
            
    cur.close()
    conn.close()

def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_proactive_messages, 'interval', minutes=30)
    scheduler.start()
    print("Local background scheduler started.")

if __name__ == "__main__":
    send_proactive_messages()
