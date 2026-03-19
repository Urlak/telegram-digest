import sqlite3
import os
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

def get_connection(db_path: str) -> sqlite3.Connection:
    """Returns a connection to the SQLite database, creating folders if needed."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(db_path: str) -> None:
    """Initializes the normalized database schema."""
    logger.info(f"Initializing database at {db_path}")
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # 1. Groups Table (Now with telegram_id)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                telegram_id TEXT UNIQUE,
                name TEXT NOT NULL
            )
        ''')
        
        # 2. Senders Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS senders (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        
        # 3. Processed Messages Table (Normalized)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                message_date TEXT NOT NULL,
                PRIMARY KEY (message_id, group_id),
                FOREIGN KEY(group_id) REFERENCES groups(id),
                FOREIGN KEY(sender_id) REFERENCES senders(id)
            )
        ''')
        
        # 4. Digests Table (Normalized)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS digests (
                group_id INTEGER PRIMARY KEY,
                digest_text TEXT NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups(id)
            )
        ''')
        
        conn.commit()

def _get_or_create_group(conn: sqlite3.Connection, telegram_id: Optional[str], group_name: str) -> int:
    """Helper to get or insert a group by ID (preferred) or name."""
    cursor = conn.cursor()
    
    # Try finding by telegram_id first
    if telegram_id:
        cursor.execute("SELECT id FROM groups WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        if row:
            # Update name if it changed
            cursor.execute("UPDATE groups SET name = ? WHERE id = ?", (group_name, row[0]))
            return row[0]
            
    # Fallback to finding by name
    cursor.execute("SELECT id FROM groups WHERE name = ?", (group_name,))
    row = cursor.fetchone()
    if row:
        if telegram_id: 
            cursor.execute("UPDATE groups SET telegram_id = ? WHERE id = ?", (telegram_id, row[0]))
        return row[0]
    
    # Create new
    cursor.execute("INSERT INTO groups (telegram_id, name) VALUES (?, ?)", (telegram_id, group_name))
    new_id = cursor.lastrowid
    assert new_id is not None
    return new_id

def _get_or_create_sender_id(conn: sqlite3.Connection, name: str) -> int:
    """Helper to get or insert a sender by name."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM senders WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row: return row[0]
    
    cursor.execute("INSERT INTO senders (name) VALUES (?)", (name,))
    new_id = cursor.lastrowid
    assert new_id is not None
    return new_id

def is_message_processed(db_path: str, message_id: int, telegram_id: Optional[str], group_name: str) -> bool:
    """Checks if a message from a specific group was already processed."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # Match by either telegram_id or name
        cursor.execute(
            """
            SELECT 1 FROM processed_messages pm
            JOIN groups g ON pm.group_id = g.id
            WHERE pm.message_id = ? AND (g.telegram_id = ? OR g.name = ?)
            """, 
            (message_id, telegram_id, group_name)
        )
        return cursor.fetchone() is not None

def mark_message_processed(
    db_path: str, 
    message_id: int, 
    telegram_id: str | None, 
    group_name: str, 
    sender_name: str, 
    message_date: str
) -> None:
    """Saves a message record using normalized foreign keys."""
    with get_connection(db_path) as conn:
        group_id = _get_or_create_group(conn, telegram_id, group_name)
        sender_id = _get_or_create_sender_id(conn, sender_name)
        
        try:
            conn.execute(
                """
                INSERT INTO processed_messages (message_id, group_id, sender_id, message_date)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, group_id, sender_id, message_date)
            )
        except sqlite3.IntegrityError:
            pass

def save_latest_digest(db_path: str, telegram_id: str | None, group_name: str, digest_text: str) -> None:
    """Saves or updates the latest generated digest for a group."""
    with get_connection(db_path) as conn:
        group_id = _get_or_create_group(conn, telegram_id, group_name)
        conn.execute(
            """
            INSERT INTO digests (group_id, digest_text, timestamp)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                digest_text=excluded.digest_text,
                timestamp=excluded.timestamp
            """,
            (group_id, digest_text, time.time())
        )

def get_latest_digest(db_path: str, target: str) -> Optional[str]:
    """Retrieves digest by matching target against telegram_id or group name."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.digest_text FROM digests d
            JOIN groups g ON d.group_id = g.id
            WHERE g.telegram_id = ? OR g.name = ?
            """, 
            (target, target)
        )
        row = cursor.fetchone()
        return row[0] if row else None


def cleanup_old_messages(db_path: str, days: int = 30) -> None:
    """Removes processed message tracking older than the specified days."""
    cutoff_date = (time.time() - (days * 86400))
    # SQLite string dates are YYYY-MM-DD HH:MM:SS, which sorts lexicographically
    formatted_cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(cutoff_date))
    
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM processed_messages WHERE message_date < ?", (formatted_cutoff,))
        count = conn.total_changes
        if count > 0:
            logger.info(f"Cleaned up {count} old message records from the database.")
        conn.commit()

