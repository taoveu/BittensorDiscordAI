"""
check_db_consistency.py
-----------------------
Checks and fixes consistency between channels.json (source of truth) and the SQLite DB.

Usage:
  python check_db_consistency.py          # Report only
  python check_db_consistency.py --fix    # Fix mismatches automatically
"""

import json
import re
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Subnet, Analysis, Message

GUILD_ID = "799672011265015819"  # Bittensor Discord server
CHANNELS_FILE = os.path.join(os.path.dirname(__file__), "channels.json")
FIX_MODE = "--fix" in sys.argv


def load_channels_json(path):
    """Parse channels.json, stripping JS-style // comments."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Remove single-line comments
    cleaned = re.sub(r'//[^\n]*', '', raw)
    return json.loads(cleaned)


def build_url(channel_id):
    return f"https://discord.com/channels/{GUILD_ID}/{channel_id}"


def main():
    print("=" * 70)
    print("  Bittensor DB ↔ channels.json Consistency Check")
    print("=" * 70)

    # 1. Load channels.json
    channels = load_channels_json(CHANNELS_FILE)
    print(f"\n📄 channels.json: {len(channels)} active channels\n")

    # Build lookup: channel_id → label
    channel_id_to_label = {cid: label for cid, label in channels.items()}
    channel_urls = {build_url(cid): cid for cid in channels}

    db = SessionLocal()
    try:
        subnets = db.query(Subnet).all()
        print(f"🗄️  DB subnets: {len(subnets)} entries\n")

        # ── 2. Subnets in DB whose discord_url is NOT in channels.json ──
        stale = [s for s in subnets if s.discord_url not in channel_urls]
        if stale:
            print(f"⚠️  STALE SUBNETS (in DB but not matching any channel in channels.json):")
            for s in stale:
                # Extract channel_id from URL
                old_cid = s.discord_url.split("/")[-1] if s.discord_url else "?"
                print(f"   DB id={s.id:4d} | {s.name:40s} | old_channel={old_cid}")
                # Check if ANY channel in channels.json has a similar name
                for cid, label in channels.items():
                    subnet_num = re.search(r'subnet\s+(\d+)', label, re.IGNORECASE)
                    db_num = re.search(r'[・・](\d+)\s*$', s.name)
                    if subnet_num and db_num and subnet_num.group(1) == db_num.group(1):
                        print(f"   ↳ Possible match in channels.json: channel={cid} ({label})")
        else:
            print("✅ No stale subnets found.")

        # ── 3. Channels in channels.json with NO matching subnet in DB ──
        db_urls = {s.discord_url for s in subnets}
        missing = {cid: label for cid, label in channels.items()
                   if build_url(cid) not in db_urls}
        if missing:
            print(f"\n⚠️  MISSING SUBNETS (in channels.json but not in DB):")
            for cid, label in missing.items():
                print(f"   channel={cid} | {label}")
        else:
            print("\n✅ All channels.json entries have a corresponding DB subnet.")

        # ── 4. Message counts per subnet ──
        print(f"\n📊 MESSAGE TABLE COUNTS (subnets with 0 messages):")
        empty_msg_subnets = []
        for s in subnets:
            count = db.query(Message).filter(Message.subnet_id == s.id).count()
            if count == 0:
                empty_msg_subnets.append(s)
        if empty_msg_subnets:
            for s in empty_msg_subnets:
                print(f"   DB id={s.id:4d} | {s.name:40s} | 0 messages in Message table")
        else:
            print("   All subnets have at least one message.")

        # ── 5. FIX MODE ──
        if FIX_MODE:
            print("\n🔧 FIX MODE: Updating stale discord_urls in DB...")
            fixed = 0
            for s in stale:
                old_cid = s.discord_url.split("/")[-1] if s.discord_url else None
                db_num = re.search(r'[・](\d+)\s*$', s.name)
                if not db_num:
                    continue
                subnet_number = db_num.group(1)
                # Find a matching channel by subnet number in label
                match_cid = None
                for cid, label in channels.items():
                    if re.search(rf'\bsubnet\s+{subnet_number}\b', label, re.IGNORECASE):
                        match_cid = cid
                        break
                if match_cid:
                    new_url = build_url(match_cid)
                    print(f"   Updating DB id={s.id} ({s.name}): {old_cid} → {match_cid}")
                    s.discord_url = new_url
                    fixed += 1
            if fixed:
                db.commit()
                print(f"\n✅ Fixed {fixed} discord_url(s) in DB.")
            else:
                print("   Nothing to auto-fix (no confident matches found).")

    finally:
        db.close()

    print("\n" + "=" * 70)
    print("  Done. Re-run with --fix to auto-correct mismatches.")
    print("=" * 70)


if __name__ == "__main__":
    main()
