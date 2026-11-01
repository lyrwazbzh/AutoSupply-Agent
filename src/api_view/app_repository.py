"""Application tables backed by the unified PostgreSQL pool."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from ..database import get_pg_pool, setup_database


class AppRepository:
    def __init__(self) -> None:
        setup_database()
        self.pool = get_pg_pool()

    def save_display_messages(self, thread_id: str, messages: list[dict]) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.display_messages(thread_id, messages, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (thread_id) DO UPDATE
                SET messages = EXCLUDED.messages, updated_at = now()
                """,
                (thread_id, Jsonb(messages)),
            )

    def get_display_messages(self, thread_id: str) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT messages FROM app.display_messages WHERE thread_id = %s",
                (thread_id,),
            )
            row = cur.fetchone()
            return list(row["messages"]) if row else []

    def save_conversation(self, thread_id: str, user_id: str, title: str) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.conversations(thread_id, user_id, title)
                VALUES (%s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    title = EXCLUDED.title,
                    updated_at = now()
                """,
                (thread_id, user_id, title),
            )

    def get_conversations(self, user_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT thread_id, user_id, title, created_at, updated_at
                FROM app.conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_conversation_user_id(self, thread_id: str) -> str | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM app.conversations WHERE thread_id = %s",
                (thread_id,),
            )
            row = cur.fetchone()
            return str(row["user_id"]) if row else None

    def delete_conversation(self, thread_id: str) -> None:
        # Audit rows are deliberately not deleted with conversation UI data.
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("DELETE FROM app.conversations WHERE thread_id = %s", (thread_id,))
                cur.execute("DELETE FROM app.display_messages WHERE thread_id = %s", (thread_id,))
                cur.execute("DELETE FROM app.harness_traces WHERE thread_id = %s", (thread_id,))

    def save_harness_trace(self, thread_id: str, trace: list[dict]) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.harness_traces(thread_id, trace, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (thread_id) DO UPDATE
                SET trace = EXCLUDED.trace, updated_at = now()
                """,
                (thread_id, Jsonb(trace)),
            )
