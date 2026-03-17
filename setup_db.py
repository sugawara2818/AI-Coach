from database_manager import init_db
import os

if __name__ == "__main__":
    if os.getenv("POSTGRES_URL"):
        print("Initializing Postgres database...")
        init_db()
        print("Done.")
    else:
        print("POSTGRES_URL not found. Please set it in your environment variables.")
