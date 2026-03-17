import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

class CoachLogic:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def generate_response(self, user_name, user_goal, user_message, chat_history=[]):
        """Generates a response to a user message."""
        prompt = f"""
        You are a supportive and professional AI Coach named 'AI Coach'. 
        The student's name is {user_name}.
        Their goal is: {user_goal}.
        
        Recent conversation history:
        {chat_history}
        
        Student says: {user_message}
        
        Provide a coaching response that encourages them, gives practical advice, and relates back to their goal. Keep it concise for a LINE message (max 200 characters if possible).
        """
        response = self.model.generate_content(prompt)
        return response.text

    def generate_proactive_message(self, user_name, user_goal):
        """Generates a proactive reminder or encouragement message."""
        prompt = f"""
        You are a supportive and professional AI Coach. 
        The student's name is {user_name}.
        Their goal is: {user_goal}.
        
        It's time for a proactive check-in. Send a very short (max 100 characters), encouraging, and actionable message to help them stay on track with their goal. 
        Don't say "Hello", just jump into the coaching.
        """
        response = self.model.generate_content(prompt)
        return response.text
