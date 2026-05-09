import os
import json
import subprocess
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv

from database import SessionLocal
from models import Subnet, Message, GlobalConfig

load_dotenv()

CHANNELS_FILE = "channels.json"
EXPORTS_DIR = "imports/"
EXPORTER_PATH = "./DiscordChatExporter.Cli"
if not os.path.exists(EXPORTER_PATH):
    EXPORTER_PATH = "../DiscordChatExporter/DiscordChatExporter.Cli"

def run_scraper(manual_channel_id=None):
    """
    Runs the DiscordChatExporter.Cli for each channel defined in channels.json,
    fetching the latest messages since the last known message in the local DB.
    """
    token = os.getenv("DISCORD_TOKEN")
    
    if not token or token == "YOUR_DISCORD_TOKEN_HERE":
        print("Scraper Error: DISCORD_TOKEN is missing or not configured in .env")
        return

    # Database initialization
    db = SessionLocal()
    
    try:
        if not manual_channel_id:
            config = db.query(GlobalConfig).filter(GlobalConfig.key == "global_scrape_enabled").first()
            if config and config.value != "True":
                print("Scraper Info: Global Scrape is DISABLED. Aborting background run.")
                return

        channels = []
        if manual_channel_id:
            channels = [str(manual_channel_id)]
        else:
            if not os.path.exists(CHANNELS_FILE):
                print(f"Scraper Error: Config file {CHANNELS_FILE} not found.")
                return
            try:
                import re
                with open(CHANNELS_FILE, "r") as f:
                    content = f.read()
                    content = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
                    channels_data = json.loads(content)
                    if isinstance(channels_data, dict):
                        channels = list(channels_data.keys())
                    elif isinstance(channels_data, list):
                        channels = channels_data
            except Exception as e:
                print(f"Scraper Error: Failed to parse {CHANNELS_FILE}: {e}")
                return

        if not channels:
            print("Scraper Warning: No channels to process.")
            return

        # Prepare default fallback date (3 days to limit data volume on first scan)
        default_after_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')

        # Prepare output dirs
        TMP_DIR = os.path.join(EXPORTS_DIR, "tmp")
        if not os.path.exists(EXPORTS_DIR):
            os.makedirs(EXPORTS_DIR)
        if not os.path.exists(TMP_DIR):
            os.makedirs(TMP_DIR)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Discord scrape for {len(channels)} target(s)...")

        for channel_id in channels:
            channel_id = str(channel_id).strip()
            if not channel_id:
                continue
                
            # Delta Logic
            after_target = default_after_date
            
            # Find subnet match
            subnet = db.query(Subnet).filter(Subnet.discord_url.endswith(f"/{channel_id}")).first()
            
            if subnet:
                # Obey subnet-level opt-in controls if this is an automated run
                if not manual_channel_id and not subnet.is_scraping_enabled:
                    print(f" -> Skipping channel {channel_id} (Auto-Scan Disabled per Subnet)")
                    continue
                    
                # Look for the absolute newest message we already know about
                latest_msg = db.query(Message).filter(Message.subnet_id == subnet.id).order_by(Message.id.desc()).first()
                if latest_msg:
                    after_target = latest_msg.id
                    
            if not subnet and not manual_channel_id:
                # If subnet doesn't exist yet, we only scrape if forcing it or if we assume it's valid globally
                pass

            tmp_path = os.path.join(TMP_DIR, f"{channel_id}.json")
            final_path = os.path.join(EXPORTS_DIR, f"{channel_id}.json")

            # Clean up any leftover tmp file from a previous failed/timed-out run
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

            command = [
                EXPORTER_PATH,
                "export",
                "-t", token,
                "-c", channel_id,
                "--after", after_target,
                "-f", "Json",
                "-o", tmp_path  # Write to tmp first
            ]

            try:
                print(f" -> Scraping channel ID: {channel_id} (After: {after_target})")
                
                # Run the command synchronously; stdout/stderr are hidden unless there's an error
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 min timeout – channels with large history can be slow
                )
                
                if result.returncode != 0:
                    print(f"    Scrape Error for {channel_id}: {result.stderr.strip()}")
                else:
                    # Write content directly to final path (instead of shutil.move)
                    # This guarantees watchdog on_modified fires reliably on macOS FSEvents,
                    # regardless of whether the destination file already exists.
                    if os.path.exists(tmp_path):
                        with open(tmp_path, 'r', encoding='utf-8') as src:
                            content = src.read()
                        with open(final_path, 'w', encoding='utf-8') as dst:
                            dst.write(content)
                        os.remove(tmp_path)
                        print(f"    Scrape Success for {channel_id}.")
                    else:
                        print(f"    Scrape Warning: DCE produced no output file for {channel_id} (0 new messages?).")

                    
            except FileNotFoundError:
                 print(f"Scraper Error: {EXPORTER_PATH} not found. Is DiscordChatExporter installed?")
                 break
            except subprocess.TimeoutExpired:
                 print(f"Scraper Error: Timeout while scraping {channel_id}.")
            except Exception as e:
                 print(f"Scraper Error: Unexpected error on {channel_id}: {e}")

        print("Discord scrape run finished.")
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    # Allows manual testing via `python scraper.py <channel_id>`
    manual_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_scraper(manual_channel_id=manual_id)
