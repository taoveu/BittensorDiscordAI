import sqlite3
import sqlalchemy
from database import engine, SessionLocal
from models import Base, GlobalConfig

def migrate():
    print("Starting database migration for Delta Ingestion features...")
    
    # 1. Add 'is_scraping_enabled' column to 'subnets' if it doesn't exist
    conn = sqlite3.connect("/Users/cvn/bittensor/BittensorDiscordAI/bsc.db")
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE subnets ADD COLUMN is_scraping_enabled BOOLEAN DEFAULT 0")
        print(" -> Added 'is_scraping_enabled' column to 'subnets' table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print(" -> Column 'is_scraping_enabled' already exists. Skipping.")
        else:
            print(f" -> Error altering table: {e}")
            
    conn.commit()
    conn.close()
    
    # 2. Create the new tables (Message, GlobalConfig) using SQLAlchemy 
    print(" -> Creating missing tables (Message, GlobalConfig) via SQLAlchemy...")
    Base.metadata.create_all(bind=engine)
    
    # 3. Seed default GlobalConfig if missing
    db = SessionLocal()
    try:
        config = db.query(GlobalConfig).filter(GlobalConfig.key == "global_scrape_enabled").first()
        if not config:
            new_config = GlobalConfig(key="global_scrape_enabled", value="False")
            db.add(new_config)
            db.commit()
            print(" -> Seeded default GlobalConfig: global_scrape_enabled = False")
    except Exception as e:
        print(f" -> Error seeding default config: {e}")
    finally:
        db.close()

    print("Migration complete!")

if __name__ == "__main__":
    migrate()
