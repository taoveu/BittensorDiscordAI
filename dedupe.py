import sqlite3

def dedupe():
    conn = sqlite3.connect("/Users/cvn/bittensor/BittensorDiscordAI/bsc.db")
    cursor = conn.cursor()
    
    # Find all discord_urls with more than one subnet entry
    cursor.execute("""
        SELECT discord_url, COUNT(*) 
        FROM subnets 
        GROUP BY discord_url 
        HAVING COUNT(*) > 1 AND discord_url IS NOT NULL;
    """)
    duplicates = cursor.fetchall()
    
    deleted_count = 0
    for url, count in duplicates:
        # Get all subnets for this URL ordered by ID (assuming highest ID is newest)
        cursor.execute("SELECT id FROM subnets WHERE discord_url = ? ORDER BY id DESC", (url,))
        ids = [row[0] for row in cursor.fetchall()]
        
        # Keep the newest (first in desc order), delete the rest
        keep_id = ids[0]
        delete_ids = ids[1:]
        
        for did in delete_ids:
            # Delete analyses for the old subnet first due to foreign key constraints
            cursor.execute("DELETE FROM analyses WHERE subnet_id = ?", (did,))
            # Delete the old subnet
            cursor.execute("DELETE FROM subnets WHERE id = ?", (did,))
            deleted_count += 1
            
    conn.commit()
    conn.close()
    
    print(f"Deduplication complete. Deleted {deleted_count} duplicate subnets.")

if __name__ == "__main__":
    dedupe()
