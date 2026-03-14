import sqlite3
import os
import logging
import time

logger = logging.getLogger(__name__)

def get_connection(db_path: str) -> sqlite3.Connection:
    """Returns a connection to the SQLite database, creating folders if needed."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path)

def init_db(db_path: str):
    """Initializes the database schema for storing processed messages and digests."""
    logger.info(f"Initializing database at {db_path}")
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # Store message_id, group_name, sender_name, and message_date 
    # to avoid mixing messages and double-processing them.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            sender_name TEXT,
            message_date TEXT NOT NULL,
            UNIQUE(message_id, group_name)
        )
    ''')
    
    # Store the latest generated digest for each group
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS digests (
            group_name TEXT PRIMARY KEY,
            digest_text TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def is_message_processed(db_path: str, message_id: int, group_name: str) -> bool:
    """Checks if a message from a specific group was already processed."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM processed_messages WHERE message_id = ? AND group_name = ?", 
        (message_id, group_name)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_message_processed(db_path: str, message_id: int, group_name: str, sender_name: str, message_date: str):
    """Saves a message record to indicate it has been processed."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO processed_messages (message_id, group_name, sender_name, message_date)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, group_name, sender_name, message_date)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Happens if we try to insert the same message twice
        pass
    finally:
        conn.close()

def save_latest_digest(db_path: str, group_name: str, digest_text: str):
    """Saves or updates the latest generated digest for a group."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO digests (group_name, digest_text, timestamp)
        VALUES (?, ?, ?)
        ON CONFLICT(group_name) DO UPDATE SET
            digest_text=excluded.digest_text,
            timestamp=excluded.timestamp
        """,
        (group_name, digest_text, time.time())
    )
    conn.commit()
    conn.close()

def get_latest_digest(db_path: str, group_name: str) -> str:
    """Retrieves the latest generated digest for a group, if any."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT digest_text FROM digests WHERE group_name = ?", (group_name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None
