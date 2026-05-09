from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
import json
import os

from database import engine, Base, get_db, SessionLocal
from models import Subnet, Analysis, GlobalConfig, Message
from ingest import start_watchdog, sync_channels_to_db
from scraper import run_scraper
from apscheduler.schedulers.background import BackgroundScheduler

Base.metadata.create_all(bind=engine)

observer = None
scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global observer, scheduler
    
    # 1. Start the Background Scheduler for Discord Scrape
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraper, 'interval', minutes=60)
    scheduler.start()
    
    # Run immediately on startup once so dashboard populates
    import threading
    threading.Thread(target=run_scraper, daemon=True).start()
    
    # 1b. Sync DB with channels.json (source of truth) before any scraping
    sync_channels_to_db()

    # 2. Start the File Watchdog for new JSON ingestion
    observer = start_watchdog()

    
    yield
    
    # 3. Graceful shutdown
    if observer:
        observer.stop()
        observer.join()
        
    if scheduler:
        scheduler.shutdown()

app = FastAPI(title="Bittensor Subnet Cockpit", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def get_channel_names():
    if os.path.exists("channels.json"):
        try:
            with open("channels.json", "r", encoding="utf-8") as f:
                import re
                content = f.read()
                content = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
                data = json.loads(content)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def calculate_advanced_fear_index(latest, all_history):
    # Guard: no score available → neutral index
    if latest.sentiment_score is None:
        return 50

    # Base math: LLM score (-1 to 1) mapped to 0-100
    base_mapped = ((latest.sentiment_score + 1.0) / 2.0) * 100

    # 0. Activity Dampener (Absolute scale)
    # Penalize low-activity channels, pushing them towards 50 (Neutral)
    authors = latest.author_count or 0
    msgs = latest.message_count or 0

    # Require at least 5 authors and 30 messages for 100% confidence
    author_factor = min(1.0, authors / 5.0)
    msg_factor = min(1.0, msgs / 30.0)

    # The final dampener is the strictest of the two
    activity_dampener = min(author_factor, msg_factor)

    # If we have no history to compare against, return the mapped AI sentiment DAMPENED
    if len(all_history) <= 1:
        dampened = 50 + ((base_mapped - 50) * activity_dampener)
        return int(max(0, min(100, dampened)))

    # 1. Activity Momentum Calculation
    # How many messages in the current scrape vs the historical average?
    current_vol = msgs

    # Consider the last 10 scrapes for the average
    recent_history = all_history[-11:-1]
    avg_vol = sum(a.message_count or 0 for a in recent_history) / len(recent_history) if recent_history else 0

    if avg_vol == 0:
        if current_vol > 0:
            momentum = 2.0  # Sudden spike from dead channel
        else:
            momentum = 0.0  # Remains dead
    else:
        momentum = current_vol / avg_vol

    # Cap the momentum multiplier at 2.5x to prevent extreme explosions
    momentum = min(momentum, 2.5)

    # 2. Weighted Application
    raw_sentiment = latest.sentiment_score  # guaranteed non-None here
    dynamic_swing = raw_sentiment * momentum * 50 * 0.75

    # Apply the absolute activity dampener to the dynamic swing
    dynamic_swing = dynamic_swing * activity_dampener

    final_index = 50 + dynamic_swing
    return int(max(0, min(100, final_index)))


@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db)):
    # Retrieve subnets with their latest analyses
    subnets = db.query(Subnet).all()
    dashboard_data = []

    channel_mappings = get_channel_names()
    
    global_config = db.query(GlobalConfig).filter(GlobalConfig.key == "global_scrape_enabled").first()
    is_global_enabled = global_config.value == "True" if global_config else False

    for subnet in subnets:
        # Get all analyses sorted chronologically
        analyses = db.query(Analysis).filter(Analysis.subnet_id == subnet.id).order_by(Analysis.created_at.asc()).all()
        
        if not analyses:
            continue
            
        latest_analysis = analyses[-1]
        
        # Build sentiment sparkline data structure
        sparkline_data = [a.sentiment_score for a in analyses]
        
        # Determine sentiment tag (Bullish=green, Neutral=yellow, Alert=red)
        # score can be None when the analysis was saved as a "scan timestamp only"
        score = latest_analysis.sentiment_score if latest_analysis.sentiment_score is not None else 0.0
        if score >= 0.3:
            sentiment_color = "green"
            sentiment_label = "Bullish"
        elif score <= -0.3:
            sentiment_color = "red"
            sentiment_label = "Alert"
        else:
            sentiment_color = "yellow"
            sentiment_label = "Neutral"


        # Calculate the Advanced Momentum-Weighted Fear Index
        fear_index = calculate_advanced_fear_index(latest_analysis, analyses)

        # Resolve display name:
        # 1. Start with the DB name as a meaningful fallback
        # 2. Override with channels.json label if the channel_id is still mapped there
        display_name = subnet.name
        channel_id = None
        default_order = 9999
        if subnet.discord_url and "/channels/" in subnet.discord_url:
            parts = subnet.discord_url.split("/")
            if len(parts) >= 2:
                channel_id = parts[-1]

        if channel_id and channel_id in channel_mappings:
            display_name = channel_mappings[channel_id]
            default_order = list(channel_mappings.keys()).index(channel_id)


        dashboard_data.append({
            "id": subnet.id,
            "name": display_name,
            "discord_url": subnet.discord_url,
            "sentiment_color": sentiment_color,
            "sentiment_label": sentiment_label,
            "sentiment_score": round(score, 2),
            "fear_index": fear_index,
            "synthesis": latest_analysis.executive_synthesis,
            "sparkline": sparkline_data,
            "created_at": latest_analysis.created_at,
            "default_order": default_order,
            "message_count": latest_analysis.message_count or 0,
            "author_count": latest_analysis.author_count or 0,
            "is_scraping_enabled": subnet.is_scraping_enabled
        })

    return templates.TemplateResponse("index.html", {
        "request": request,
        "subnets": dashboard_data,
        "global_scrape_enabled": is_global_enabled
    })

@app.get("/subnet/{subnet_id}")
def read_subnet_detail(request: Request, subnet_id: int, db: Session = Depends(get_db)):
    subnet = db.query(Subnet).filter(Subnet.id == subnet_id).first()
    if not subnet:
        return {"error": "Subnet not found"}
        
    latest_analysis = db.query(Analysis).filter(Analysis.subnet_id == subnet_id).order_by(Analysis.created_at.desc()).first()

    view_name = subnet.name
    fear_index = None
    if latest_analysis:
        if latest_analysis.raw_json_file:
            view_name = latest_analysis.raw_json_file.replace('.json', '')
            
        # Calculate Fear Index matching the dashboard logic (we need all history here too)
        all_analyses = db.query(Analysis).filter(Analysis.subnet_id == subnet_id).order_by(Analysis.created_at.asc()).all()
        fear_index = calculate_advanced_fear_index(latest_analysis, all_analyses)
        
    # Apply friendly name mapped from configuration
    channel_mappings = get_channel_names()
    channel_id = None
    if subnet.discord_url and "/channels/" in subnet.discord_url:
        parts = subnet.discord_url.split("/")
        if len(parts) >= 2:
            channel_id = parts[-1]
            
    if channel_id and channel_id in channel_mappings:
        view_name = channel_mappings[channel_id]

    return templates.TemplateResponse("detail.html", {
        "request": request,
        "subnet": subnet,
        "view_name": view_name,
        "analysis": latest_analysis,
        "fear_index": fear_index,
        "last_message_at": db.query(Message).filter(Message.subnet_id == subnet_id).order_by(Message.timestamp.desc()).first()
    })

# --- Scraper API Controls ---

@app.post("/api/toggle-global-scrape")
def toggle_global_scrape(request: Request, db: Session = Depends(get_db)):
    config = db.query(GlobalConfig).filter(GlobalConfig.key == "global_scrape_enabled").first()
    if not config:
        config = GlobalConfig(key="global_scrape_enabled", value="False")
        db.add(config)
    
    new_state = "True" if config.value == "False" else "False"
    config.value = new_state
    db.commit()
    return {"status": "success", "global_scrape_enabled": new_state == "True"}

@app.post("/api/subnet/{subnet_id}/toggle-scrape")
def toggle_subnet_scrape(subnet_id: int, db: Session = Depends(get_db)):
    subnet = db.query(Subnet).filter(Subnet.id == subnet_id).first()
    if not subnet:
        return {"error": "Subnet not found"}
        
    subnet.is_scraping_enabled = not subnet.is_scraping_enabled
    db.commit()
    return {"status": "success", "is_scraping_enabled": subnet.is_scraping_enabled}

@app.post("/api/subnet/{subnet_id}/scan-now")
def trigger_manual_scan(subnet_id: int, db: Session = Depends(get_db)):
    subnet = db.query(Subnet).filter(Subnet.id == subnet_id).first()
    if not subnet:
        return {"error": "Subnet not found"}
        
    # Extract channel ID from discord_url
    channel_id = None
    if subnet.discord_url and "/channels/" in subnet.discord_url:
        parts = subnet.discord_url.split("/")
        if len(parts) >= 2:
            channel_id = parts[-1]
            
    if not channel_id:
        return {"error": "Invalid Discord URL on subnet"}
        
    import subprocess
    import sys
    # Use the same Python interpreter as the running server (correct venv)
    scraper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper.py")
    subprocess.Popen(
        [sys.executable, scraper_path, channel_id],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    return {"status": "success", "message": "Background scan started"}
