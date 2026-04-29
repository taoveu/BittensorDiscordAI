import sqlite3
import os

DB_PATH = "/Users/cvn/bittensor/BittensorDiscordAI/bsc.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database not found, nothing to migrate.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(analyses)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "author_count" not in columns:
        print("Adding author_count column to analyses table...")
        cursor.execute("ALTER TABLE analyses ADD COLUMN author_count INTEGER DEFAULT 0")
        conn.commit()
        print("Migration applied successfully.")
    else:
        print("Column 'author_count' already exists.")
        
    conn.close()

if __name__ == "__main__":
    migrate()
