import time
import json
import re
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Subnet, Analysis, Message
from datetime import datetime
from ai_agent import analyze_discord_exchanges

IMPORTS_DIR = "./imports"
CHANNELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channels.json")


def get_channel_names() -> dict:
    """Parse channels.json (source of truth) and return {channel_id: label}."""
    try:
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
            raw = f.read()
        # Strip JS-style // comments
        cleaned = re.sub(r'//[^\n]*', '', raw)
        return json.loads(cleaned)
    except Exception as e:
        print(f"⚠️  Could not load channels.json: {e}")
        return {}



class JsonHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.last_processed = {}
        self.debounce_seconds = 5

    def _should_process(self, filepath):
        current_time = time.time()
        if filepath in self.last_processed:
            if current_time - self.last_processed[filepath] < self.debounce_seconds:
                return False
        self.last_processed[filepath] = current_time
        return True

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.json'):
            if self._should_process(event.src_path):
                print(f"New JSON file detected: {event.src_path}")
                # Wait a tiny bit to ensure file is fully written before reading
                time.sleep(0.5)
                self.process_file(event.src_path)

    def on_modified(self, event):
         if not event.is_directory and event.src_path.endswith('.json'):
            if self._should_process(event.src_path):
                print(f"Modified JSON file detected: {event.src_path}")
                time.sleep(0.5)
                self.process_file(event.src_path)

    def on_moved(self, event):
        # shutil.move() from tmp/ to imports/ is a rename → fires on_moved, not on_created
        if not event.is_directory and event.dest_path.endswith('.json'):
            # Only process files moved INTO the imports root (not inside tmp/)
            dest_dir = os.path.dirname(event.dest_path)
            if not dest_dir.endswith('/tmp') and not dest_dir.endswith(os.sep + 'tmp'):
                if self._should_process(event.dest_path):
                    print(f"Moved JSON file detected: {event.dest_path}")
                    time.sleep(0.5)
                    self.process_file(event.dest_path)


    def process_file(self, filepath):
        # Quick sanity check: empty file = corrupted/incomplete write
        try:
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                print(f"⚠️  Empty file detected, deleting: {filepath}")
                os.remove(filepath)
                return
        except Exception as e:
            print(f"Error checking file size for {filepath}: {e}")
            return

        # Try to parse JSON with a short retry window (file might still be finalizing)
        max_retries = 3
        data = None
        for attempt in range(max_retries):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                break
            except json.JSONDecodeError:
                if attempt < max_retries - 1:
                    print(f"JSON not ready yet for {filepath}, retrying in 2s... ({attempt + 1}/{max_retries})")
                    time.sleep(2.0)
                else:
                    print(f"❌ Corrupted JSON file after {max_retries * 2}s: {filepath}. Deleting to avoid reprocessing.")
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                    return
            except Exception as e:
                print(f"Error opening file {filepath}: {e}")
                return

        if not data:
            return

        try:
            # Support DiscordChatExporter format or explicit URL
            guild_id = data.get("guild", {}).get("id")
            channel_id = data.get("channel", {}).get("id")
            channel_name = data.get("channel", {}).get("name")

            # Resolve subnet name: prefer explicit > DCE channel name > channels.json lookup > filename
            raw_fallback = os.path.basename(filepath).replace(".json", "")
            subnet_name = data.get("subnet_name") or channel_name

            if not subnet_name or subnet_name.isdigit():
                # Fallback is a numeric channel ID — look up the human-readable label
                lookup_id = channel_id or raw_fallback
                channel_mappings = get_channel_names()
                subnet_name = channel_mappings.get(str(lookup_id), raw_fallback)


            if "discord_url" in data:
                discord_url = data["discord_url"]
            elif guild_id and channel_id:
                discord_url = f"https://discord.com/channels/{guild_id}/{channel_id}"
            else:
                discord_url = "https://discord.com/channels/@me"
            
            # Save to DB and manage Message Cache
            db = SessionLocal()
            try:
                # 1. Find or create Subnet
                # Priority: exact discord_url match → name match (channel renamed) → create new
                subnet = db.query(Subnet).filter(Subnet.discord_url == discord_url).first()
                if not subnet:
                    # Check if a subnet with the same name already exists (channel was renamed)
                    # In that case, update its discord_url instead of creating a duplicate
                    subnet_by_name = db.query(Subnet).filter(Subnet.name == subnet_name).first()
                    if subnet_by_name:
                        print(f"  ℹ️ Subnet '{subnet_name}' exists with different URL. "
                              f"Old file for renamed channel — skipping to avoid conflict.")
                        return  # Old file for a channel that has since moved; skip silently
                    try:
                        subnet = Subnet(name=subnet_name, discord_url=discord_url)
                        db.add(subnet)
                        db.commit()
                        db.refresh(subnet)
                    except Exception as create_err:
                        db.rollback()
                        print(f"  ⚠️ Could not create subnet '{subnet_name}': {create_err} — skipping file.")
                        return
                else:
                    # Update name if the Discord channel was renamed
                    if subnet.name != subnet_name:
                        subnet.name = subnet_name
                        db.commit()


                # 2. Persist new Messages to Cache
                # Insert ALL messages (even media-only) for delta tracking and last_message_at.
                # Content-filtering happens at AI context step, not here.
                raw_messages = data.get("messages", [])
                new_msg_count = 0
                for msg in raw_messages:
                    if isinstance(msg, dict):
                        msg_id = msg.get("id")
                        content = msg.get("content", "") or ""
                        author_name = msg.get("author", {}).get("name", "Unknown")
                        ts_str = msg.get("timestamp")

                        if not msg_id:
                            continue

                        # Parse ISO8601 Discord timestamp
                        try:
                            ts = datetime.fromisoformat(ts_str)
                        except Exception:
                            ts = datetime.utcnow()

                        # Insert if it doesn't exist
                        existing = db.query(Message).filter(Message.id == msg_id).first()
                        if not existing:
                            db.add(Message(
                                id=msg_id,
                                subnet_id=subnet.id,
                                author=author_name,
                                content=content,  # may be empty string — that's OK
                                timestamp=ts
                            ))
                            new_msg_count += 1

                if new_msg_count > 0:
                    db.commit()
                print(f"Inserted {new_msg_count} new delta messages for {subnet_name}")

                # 3. Retrieve sliding window of historical context from DB
                # Only messages WITH text content are passed to the AI.
                history = db.query(Message).filter(
                    Message.subnet_id == subnet.id,
                    Message.content != "",
                    Message.content != None
                ).order_by(Message.timestamp.desc()).limit(150).all()
                history.reverse()  # chronological order for AI

                messages_arr = []
                unique_authors = set()

                for h in history:
                    if h.author != "Unknown":
                        unique_authors.add(h.author)
                    if h.content and str(h.content).strip():
                        messages_arr.append(f"{h.author}: {h.content}")


                    
                raw_msg_count = len(messages_arr)
                messages_text = "\n".join(messages_arr)

                if not messages_text:
                    # Fallback: DB is empty for this subnet (e.g. first scan with new code).
                    # Try to build the context directly from the JSON file we just loaded.
                    print(f"⚠️ Message table empty for {subnet_name}. Falling back to JSON file content.")
                    fallback_inserts = 0
                    for msg in raw_messages:
                        if isinstance(msg, dict):
                            msg_id = msg.get("id")
                            content = msg.get("content", "")
                            author_name = msg.get("author", {}).get("name", "Unknown")
                            ts_str = msg.get("timestamp")
                            if author_name != "Unknown":
                                unique_authors.add(author_name)
                            if content and str(content).strip() != "":
                                messages_arr.append(f"{author_name}: {content}")
                                # Also insert into Message table so last_message_at works
                                if msg_id and not db.query(Message).filter(Message.id == msg_id).first():
                                    try:
                                        ts = datetime.fromisoformat(ts_str) if ts_str else datetime.utcnow()
                                    except Exception:
                                        ts = datetime.utcnow()
                                    db.add(Message(id=msg_id, subnet_id=subnet.id, author=author_name, content=content, timestamp=ts))
                                    fallback_inserts += 1
                    if fallback_inserts > 0:
                        db.commit()
                        print(f"  Inserted {fallback_inserts} messages from JSON fallback into Message table.")
                    raw_msg_count = len(messages_arr)
                    messages_text = "\n".join(messages_arr)


                if not messages_text:
                    # Truly empty - channel has no analyzable text content at all
                    print(f"⚠️ No text messages in JSON either for {subnet_name}. Saving scan timestamp only.")
                    # Keep previous analysis score but record a new scan was done
                    prev_analysis = db.query(Analysis).filter(Analysis.subnet_id == subnet.id).order_by(Analysis.created_at.desc()).first()
                    prev_score = prev_analysis.sentiment_score if prev_analysis else None
                    prev_synthesis = prev_analysis.executive_synthesis if prev_analysis else "Aucun message textuel détecté dans ce subnet."
                    prev_points = prev_analysis.critical_points if prev_analysis else ["Canal sans activité textuelle détectable."]
                    analysis = Analysis(
                        subnet_id=subnet.id,
                        sentiment_score=prev_score,
                        executive_synthesis=prev_synthesis,
                        critical_points=prev_points,
                        raw_json_file=os.path.basename(filepath),
                        author_count=0,
                        message_count=0
                    )
                    db.add(analysis)
                    db.commit()
                    print(f"✅ Scan timestamp updated for {subnet_name} (no text content)")
                    return

                # 4. Trigger AI Analysis
                # Use last 30 msgs for sentiment score, full 150 for context/synthesis
                recent_slice = messages_arr[-30:] if len(messages_arr) > 30 else messages_arr
                recent_messages_text = "\n".join(recent_slice)

                print(f"Analyzing {len(messages_arr)} historical messages for subnet {subnet_name} (sentiment based on last {len(recent_slice)})...")
                result = analyze_discord_exchanges(messages_text, recent_messages_text)

                
                # 5. Save Analysis Result
                analysis = Analysis(
                    subnet_id=subnet.id,
                    sentiment_score=result.get("sentiment_score", 0.0),
                    executive_synthesis=result.get("executive_synthesis", "Error getting synthesis"),
                    critical_points=result.get("critical_points", []),
                    raw_json_file=os.path.basename(filepath),
                    author_count=len(unique_authors),
                    message_count=raw_msg_count
                )
                db.add(analysis)
                db.commit()
                print(f"✅ Successfully processed and saved analysis for {subnet_name}")

                
            except Exception as e:
                db.rollback()
                print(f"Database error while saving analysis: {e}")
            finally:
                db.close()
                
        except Exception as e:
            print(f"Error processing file {filepath}: {e}")

def sync_channels_to_db():
    """
    Synchronise la base de données avec channels.json (source de vérité).

    Pour chaque entrée de channels.json, on extrait le numéro de subnet et on
    compare avec la DB. Si le channel_id ou le nom a changé, on met à jour la DB
    et on supprime le vieux fichier JSON de cache pour forcer un nouveau scrape.

    Clé de correspondance stable : le numéro de subnet (ex: 82, 102…)
    """
    import re

    channel_mappings = get_channel_names()   # {channel_id: "label - subnet N"}
    guild_id = "799672011265015819"

    # Index channels.json par numéro de subnet → (new_channel_id, new_label)
    channels_by_sn: dict[int, tuple[str, str]] = {}
    for cid, label in channel_mappings.items():
        m = re.search(r'\bsubnet\s+(\d+)\b', label, re.IGNORECASE)
        if m:
            channels_by_sn[int(m.group(1))] = (cid, label)

    db = SessionLocal()
    updated = 0
    try:
        subnets = db.query(Subnet).all()
        for subnet in subnets:
            if not subnet.discord_url:
                continue

            db_channel_id = subnet.discord_url.rstrip('/').split('/')[-1]

            # Extract subnet number from DB name (handles ・82, ・ex66, etc.)
            m = re.search(r'(?:ex)?(\d+)\s*$', subnet.name)
            if not m:
                continue
            sn = int(m.group(1))

            if sn not in channels_by_sn:
                continue  # Subnet not configured in channels.json — skip

            new_cid, new_label = channels_by_sn[sn]
            new_url = f"https://discord.com/channels/{guild_id}/{new_cid}"

            # Check for name conflict BEFORE making any changes
            if subnet.name != new_label:
                conflicting_subnet = db.query(Subnet).filter(Subnet.name == new_label).first()
                if conflicting_subnet and conflicting_subnet.id != subnet.id:
                    print(f"  ⚠️ Conflict: Subnet '{new_label}' already exists (ID {conflicting_subnet.id}). Merging...")
                    # Transfer messages and analyses to the existing subnet
                    db.query(Message).filter(Message.subnet_id == subnet.id).update({Message.subnet_id: conflicting_subnet.id})
                    db.query(Analysis).filter(Analysis.subnet_id == subnet.id).update({Analysis.subnet_id: conflicting_subnet.id})
                    db.delete(subnet)
                    print(f"  🗑️ Deleted duplicate subnet ID {subnet.id}")
                    updated += 1
                    continue # Skip to next subnet, this one is gone

            changed = False

            if db_channel_id != new_cid:
                print(f"🔄 [sync] SN{sn}: channel {db_channel_id} → {new_cid}  ({subnet.name} → {new_label})")
                # Remove old JSON cache so next scan fetches from the new channel
                old_cache = os.path.join(IMPORTS_DIR, f"{db_channel_id}.json")
                if os.path.exists(old_cache):
                    os.remove(old_cache)
                    print(f"  🗑️  Removed stale cache: {old_cache}")
                subnet.discord_url = new_url
                changed = True

            if subnet.name != new_label:
                print(f"  ✏️  Renaming SN{sn}: '{subnet.name}' → '{new_label}'")
                subnet.name = new_label
                changed = True


            if changed:
                updated += 1

        if updated:
            db.commit()
            print(f"✅ [sync] {updated} subnet(s) updated from channels.json")
        else:
            print("✅ [sync] DB is already in sync with channels.json")
    except Exception as e:
        db.rollback()
        print(f"❌ [sync] Error during sync: {e}")
    finally:
        db.close()


def start_watchdog():

    if not os.path.exists(IMPORTS_DIR):
        os.makedirs(IMPORTS_DIR)
        
    event_handler = JsonHandler()
    observer = Observer()
    observer.schedule(event_handler, path=IMPORTS_DIR, recursive=False)
    observer.start()
    print(f"Started monitoring {IMPORTS_DIR} for JSON files...")

    # Process any existing JSON files that don't yet have a subnet in the DB
    import threading
    def _process_existing():
        from database import SessionLocal
        from models import Subnet
        db = SessionLocal()
        try:
            existing_urls = {s.discord_url for s in db.query(Subnet).all()}
        finally:
            db.close()

        existing_files = [
            f for f in os.listdir(IMPORTS_DIR)
            if f.endswith('.json') and not f.startswith('.')
        ]
        for fname in existing_files:
            # Extract channel_id from filename to check if already in DB
            channel_id = fname.replace('.json', '')
            already_known = any(url.endswith(f'/{channel_id}') for url in existing_urls)
            if not already_known:
                fpath = os.path.join(IMPORTS_DIR, fname)
                print(f"📂 Processing pre-existing file without subnet entry: {fname}")
                event_handler.process_file(fpath)

    threading.Thread(target=_process_existing, daemon=True).start()

    return observer
