"""SQLite database for Penny."""

import json
import os
import aiosqlite
from pathlib import Path
from typing import Optional
from datetime import datetime

from .models import Item

DATABASE_PATH = Path(os.environ.get("PENNY_DB_PATH", "/app/data/penny.db"))


async def init_db():
    """Initialize the database schema."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'unknown',
                confidence REAL NOT NULL DEFAULT 0.0,
                source_file TEXT,
                created_at TEXT NOT NULL,
                routed_to TEXT,
                status TEXT NOT NULL DEFAULT 'processed',
                routing_data TEXT
            )
        """)
        # Add new columns to existing tables BEFORE creating indexes
        # (no-op if they already exist)
        try:
            await db.execute("ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'processed'")
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE items ADD COLUMN routing_data TEXT")
        except Exception:
            pass  # Column already exists

        # Create indexes after columns are ensured to exist
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_created_at
            ON items(created_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_classification
            ON items(classification)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_status
            ON items(status)
        """)

        # Claude Code build sessions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS claude_sessions (
                id TEXT PRIMARY KEY,
                transcript TEXT NOT NULL,
                model_used TEXT,
                status TEXT DEFAULT 'running',
                result TEXT,
                deliverables TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_claude_sessions_status
            ON claude_sessions(status)
        """)

        # Learned preferences from builds
        await db.execute("""
            CREATE TABLE IF NOT EXISTS learned_preferences (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                source_transcript TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_learned_preferences_key
            ON learned_preferences(key)
        """)

        # Pending Telegram questions for build Q&A
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_questions (
                id TEXT PRIMARY KEY,
                build_id TEXT NOT NULL,
                question TEXT NOT NULL,
                message_id TEXT,
                created_at TEXT NOT NULL,
                answered_at TEXT,
                answer TEXT
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_questions_build_id
            ON pending_questions(build_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_questions_message_id
            ON pending_questions(message_id)
        """)

        await db.commit()


async def save_item(item: Item) -> Item:
    """Save an item to the database."""
    routing_data_json = json.dumps(item.routing_data) if item.routing_data else None
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO items (id, text, classification, confidence, source_file, created_at, routed_to, status, routing_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.text,
                item.classification,
                item.confidence,
                item.source_file,
                item.created_at.isoformat(),
                item.routed_to,
                item.status,
                routing_data_json,
            ),
        )
        await db.commit()
    return item


def _row_to_item(row) -> Item:
    """Convert a database row to an Item."""
    routing_data = None
    if row["routing_data"]:
        try:
            routing_data = json.loads(row["routing_data"])
        except json.JSONDecodeError:
            pass
    return Item(
        id=row["id"],
        text=row["text"],
        classification=row["classification"],
        confidence=row["confidence"],
        source_file=row["source_file"],
        created_at=datetime.fromisoformat(row["created_at"]),
        routed_to=row["routed_to"],
        status=row["status"] if "status" in row.keys() else "processed",
        routing_data=routing_data,
    )


async def get_item(item_id: str) -> Optional[Item]:
    """Get an item by ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return _row_to_item(row)
    return None


async def get_items(
    page: int = 1,
    per_page: int = 50,
    classification: Optional[str] = None,
) -> tuple[list[Item], int]:
    """Get paginated items."""
    offset = (page - 1) * per_page

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Build query
        where_clause = ""
        params = []
        if classification:
            where_clause = "WHERE classification = ?"
            params.append(classification)

        # Get total count
        async with db.execute(
            f"SELECT COUNT(*) as count FROM items {where_clause}", params
        ) as cursor:
            row = await cursor.fetchone()
            total = row["count"]

        # Get items
        async with db.execute(
            f"""
            SELECT * FROM items {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ) as cursor:
            rows = await cursor.fetchall()
            items = [_row_to_item(row) for row in rows]

    return items, total


async def update_classification(item_id: str, classification: str) -> Optional[Item]:
    """Update an item's classification."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE items SET classification = ?, confidence = 1.0 WHERE id = ?",
            (classification, item_id),
        )
        await db.commit()

    return await get_item(item_id)


async def update_routed_to(item_id: str, routed_to: str, status: str = "processed") -> Optional[Item]:
    """Update an item's routing destination and status."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE items SET routed_to = ?, status = ? WHERE id = ?",
            (routed_to, status, item_id),
        )
        await db.commit()

    return await get_item(item_id)


async def update_status(item_id: str, status: str) -> Optional[Item]:
    """Update an item's status."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE items SET status = ? WHERE id = ?",
            (status, item_id),
        )
        await db.commit()

    return await get_item(item_id)


async def get_pending_items() -> list[Item]:
    """Get all items pending confirmation."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM items WHERE status = 'pending_confirmation' ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_item(row) for row in rows]


# =============================================================================
# Claude Sessions CRUD
# =============================================================================


async def save_claude_session(
    session_id: str,
    transcript: str,
    model_used: str,
    status: str = "running",
) -> dict:
    """Create a new Claude Code build session."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO claude_sessions (id, transcript, model_used, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, transcript, model_used, status, now, now),
        )
        await db.commit()
    return {
        "id": session_id,
        "transcript": transcript,
        "model_used": model_used,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }


async def update_claude_session(
    session_id: str,
    status: Optional[str] = None,
    result: Optional[str] = None,
    deliverables: Optional[list] = None,
) -> Optional[dict]:
    """Update a Claude Code build session."""
    now = datetime.utcnow().isoformat()
    updates = ["updated_at = ?"]
    params = [now]

    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if result is not None:
        updates.append("result = ?")
        params.append(result)
    if deliverables is not None:
        updates.append("deliverables = ?")
        params.append(json.dumps(deliverables))

    params.append(session_id)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            f"UPDATE claude_sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()

    return await get_claude_session(session_id)


async def get_claude_session(session_id: str) -> Optional[dict]:
    """Get a Claude Code build session by ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM claude_sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                deliverables = None
                if row["deliverables"]:
                    try:
                        deliverables = json.loads(row["deliverables"])
                    except json.JSONDecodeError:
                        pass
                return {
                    "id": row["id"],
                    "transcript": row["transcript"],
                    "model_used": row["model_used"],
                    "status": row["status"],
                    "result": row["result"],
                    "deliverables": deliverables,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
    return None


# =============================================================================
# Learned Preferences CRUD
# =============================================================================


async def save_learned_preference(
    key: str,
    value: str,
    source_transcript: Optional[str] = None,
) -> dict:
    """Save a learned preference."""
    import uuid

    pref_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO learned_preferences (id, key, value, source_transcript, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pref_id, key, value, source_transcript, now),
        )
        await db.commit()

    return {"id": pref_id, "key": key, "value": value, "created_at": now}


async def get_learned_preferences() -> list[dict]:
    """Get all learned preferences."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM learned_preferences ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "key": row["key"],
                    "value": row["value"],
                    "source_transcript": row["source_transcript"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]


async def get_preference_by_key(key: str) -> Optional[dict]:
    """Get the most recent preference for a key."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM learned_preferences WHERE key = ? ORDER BY created_at DESC LIMIT 1",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "key": row["key"],
                    "value": row["value"],
                    "source_transcript": row["source_transcript"],
                    "created_at": row["created_at"],
                }
    return None


# =============================================================================
# Pending Questions CRUD
# =============================================================================


async def save_pending_question(
    build_id: str,
    question: str,
    message_id: Optional[str] = None,
) -> dict:
    """Save a pending question for Telegram Q&A."""
    import uuid

    question_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            INSERT INTO pending_questions (id, build_id, question, message_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (question_id, build_id, question, message_id, now),
        )
        await db.commit()

    return {
        "id": question_id,
        "build_id": build_id,
        "question": question,
        "message_id": message_id,
        "created_at": now,
    }


async def get_pending_question_by_build_id(build_id: str) -> Optional[dict]:
    """Get pending question for a build."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_questions WHERE build_id = ? AND answered_at IS NULL",
            (build_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "build_id": row["build_id"],
                    "question": row["question"],
                    "message_id": row["message_id"],
                    "created_at": row["created_at"],
                }
    return None


async def get_pending_question_by_message_id(message_id: str) -> Optional[dict]:
    """Get pending question by Telegram message ID."""
    if not message_id:
        return None

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_questions WHERE message_id = ? AND answered_at IS NULL",
            (str(message_id),),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "build_id": row["build_id"],
                    "question": row["question"],
                    "message_id": row["message_id"],
                    "created_at": row["created_at"],
                }
    return None


async def mark_question_answered(question_id: str, answer: str) -> Optional[dict]:
    """Mark a pending question as answered."""
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE pending_questions SET answered_at = ?, answer = ? WHERE id = ?",
            (now, answer, question_id),
        )
        await db.commit()

        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_questions WHERE id = ?", (question_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "build_id": row["build_id"],
                    "question": row["question"],
                    "answer": row["answer"],
                    "answered_at": row["answered_at"],
                }
    return None


async def delete_pending_question(build_id: str) -> bool:
    """Delete pending question for a build."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM pending_questions WHERE build_id = ?", (build_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
