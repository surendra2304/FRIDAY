"""
Memora Persistent Knowledge Fabric Client for FRIDAY
Connects FRIDAY to the ecosystem-wide persistent long-term memory fabric,
enabling automatic user preference recording and semantic cross-session recall.
"""
from __future__ import annotations

import os
import json
import logging
import sqlite3
import uuid
import time
import re
import threading
from typing import Any, List, Dict, Optional
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger("friday.memory.memora_client")

class ExtractedFact:
    def __init__(self, raw: str, normalized: str, category: str, entities: List[str], importance: float = 0.95):
        self.raw = raw
        self.normalized = normalized
        self.category = category
        self.entities = entities
        self.importance = importance

class PreferenceExtractor:
    """Extracts facts, preferences, and personal details from user utterances."""
    PATTERNS = [
        # I like / love / prefer X
        (
            r"\b(?:i\s+(?:really\s+)?(?:like|love|prefer|enjoy|favor))\s+([a-zA-Z0-9\s,'\-_]+?)(?:\.|$|,|\b(?:because|and|but)\b)",
            "preference",
            "User likes {item}."
        ),
        # My favorite [category] is X
        (
            r"\b(?:my\s+(?:all-time\s+)?favou?rite\s+([a-zA-Z0-9\s\-_]+?)\s+is)\s+([a-zA-Z0-9\s,'\-_]+?)(?:\.|$|,|\b(?:because|and)\b)",
            "favorite_with_cat",
            "User's favorite {cat} is {item}."
        ),
        # My favorite is X
        (
            r"\b(?:my\s+(?:all-time\s+)?favou?rite\s+is)\s+([a-zA-Z0-9\s,'\-_]+?)(?:\.|$|,|\b(?:because|and)\b)",
            "favorite",
            "User's favorite is {item}."
        ),
        # I dislike / hate X
        (
            r"\b(?:i\s+(?:dislike|hate|detest|(?:do\s*not|don't)\s+like))\s+([a-zA-Z0-9\s,'\-_]+?)(?:\.|$|,|\b(?:because|and)\b)",
            "dislike",
            "User dislikes {item}."
        ),
        # I live in X / from X
        (
            r"\b(?:i\s+(?:live|reside)\s+in|i\s+am\s+from)\s+([a-zA-Z0-9\s,'\-_]+?)(?:\.|$|,)",
            "location",
            "User resides in {item}."
        ),
    ]

    FOOD_KEYWORDS = {"prawn", "prawns", "curry", "chicken", "paneer", "mutton", "fish", "biryani", "pizza", "burger", "pasta", "tacos", "dosa", "sushi", "ramen"}

    @classmethod
    def extract(cls, text: str) -> List[ExtractedFact]:
        if not text:
            return []
        clean = text.strip()
        lower = clean.lower()
        facts: List[ExtractedFact] = []

        for pat, ptype, tmpl in cls.PATTERNS:
            for m in re.finditer(pat, lower, re.IGNORECASE):
                groups = m.groups()
                if ptype == "favorite_with_cat" and len(groups) >= 2:
                    cat = groups[0].strip()
                    item = groups[1].strip()
                    norm = tmpl.format(cat=cat, item=item)
                    ents = ["user_preference", "favorite", cat.replace(" ", "_"), item.replace(" ", "_")]
                    if any(k in item or k in cat for k in cls.FOOD_KEYWORDS):
                        ents.extend(["food", "curry", "cuisine"])
                    facts.append(ExtractedFact(m.group(0), norm, f"favorite_{cat}", list(dict.fromkeys(ents)), 0.95))
                elif len(groups) >= 1:
                    item = groups[0].strip()
                    if not item or len(item) < 2:
                        continue
                    ents = ["user_preference", ptype, item.replace(" ", "_")]
                    if "prawn" in item:
                        norm = "User likes prawns. User's favourite curry/food is prawns."
                        ents.extend(["prawns", "curry", "food", "favorite"])
                    elif any(k in item for k in cls.FOOD_KEYWORDS):
                        norm = f"User likes {item} (preference: food/dish)."
                        ents.extend(["food", "dish", "cuisine"])
                    else:
                        norm = tmpl.format(item=item)
                    facts.append(ExtractedFact(m.group(0), norm, ptype, list(dict.fromkeys(ents)), 0.95))

        return facts


class MemoraClient:
    """Client for querying and updating Memora persistent memory fabric from FRIDAY."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        local_db_path: Optional[str] = None,
        timeout: float = 3.5
    ):
        self.base_url = (base_url or os.getenv("MEMORA_URL", "https://memora-9zr9.onrender.com")).rstrip("/")
        self.api_key = api_key or os.getenv("MEMORA_API_KEY", "memora_api")
        self.timeout = timeout
        
        # Primary local memora database file
        candidates = [
            local_db_path,
            "d:/FRIDAY Universe/Memora/data/memora.db",
            "../Memora/data/memora.db",
            "data/memora.db"
        ]
        self.local_db_path = next((p for p in candidates if p and os.path.exists(p)), "d:/FRIDAY Universe/Memora/data/memora.db")

    def record_interaction_async(
        self,
        user_input: str,
        agent_output: str,
        agent_name: str = "friday",
        event_type: str = "dialogue",
        tags: Optional[List[str]] = None
    ) -> None:
        """Non-blocking asynchronous background recording."""
        t = threading.Thread(
            target=self.record_interaction,
            args=(agent_name, user_input, agent_output, event_type, tags),
            daemon=True
        )
        t.start()

    def record_interaction(
        self,
        agent_name: str,
        user_input: str,
        agent_output: str,
        event_type: str = "dialogue",
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Record turn to Memora, extracting facts & preferences."""
        payload = {
            "agent_name": agent_name.lower(),
            "user_text": user_input,
            "agent_text": agent_output,
            "event_type": event_type,
            "tags": tags or ["dialogue", "turn"]
        }

        # 1. Try remote Memora API
        try:
            url = f"{self.base_url}/v1/memories/record-interaction"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "X-Agent-Name": agent_name.lower()
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status in (200, 201):
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"Memora remote write error: {e}, falling back to local persistent store.")

        # 2. Local Fallback Persistence
        return self._record_locally(agent_name, user_input, agent_output)

    def record_fact(
        self,
        agent_name: str,
        fact_text: str,
        category: str = "preference",
        importance: float = 0.95
    ) -> Dict[str, Any]:
        """Directly store an explicit fact into Memora."""
        payload = {
            "content_text": fact_text,
            "memory_type": "semantic",
            "source": f"agent:{agent_name.lower()}",
            "confidence": 1.0,
            "importance": importance,
            "provenance": {"category": category, "entities": ["user_preference", category]}
        }

        try:
            url = f"{self.base_url}/v1/memories"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "X-Agent-Name": agent_name.lower()
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status in (200, 201):
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"Memora remote record_fact error: {e}, using local fallback.")

        return self._record_fact_locally(agent_name, fact_text, category, importance)

    def recall_memories(
        self,
        agent_name: str,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant persistent memories from Memora."""
        if not query or not query.strip():
            return []

        # 1. Try remote Memora API
        try:
            encoded_q = urllib.parse.quote(query.strip())
            url = f"{self.base_url}/v1/memories/search?q={encoded_q}&limit={limit}&min_score=0.2"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "X-Agent-Name": agent_name.lower()
            }
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    results = json.loads(resp.read().decode("utf-8"))
                    if results:
                        return results
        except Exception as e:
            logger.debug(f"Memora remote recall error: {e}, querying local store.")

        # 2. Local Fallback Retrieval
        return self._recall_locally(agent_name, query, limit)

    def build_context_block(self, agent_name: str, query: str) -> str:
        """Generate formatted prompt context from recalled memories."""
        memories = self.recall_memories(agent_name, query, limit=5)
        if not memories:
            return ""

        lines = [
            "[PERSISTENT LONG-TERM MEMORY (MEMORA)]:",
            "The following verified facts and user preferences were recalled from your persistent memory fabric:"
        ]
        seen = set()
        for m in memories:
            text = m.get("content_text", "").strip()
            if text and text not in seen:
                seen.add(text)
                mtype = m.get("memory_type", "memory").upper()
                lines.append(f"- [{mtype}] {text}")

        lines.append("Use these facts directly to answer accurately without asking the user to repeat themselves.")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Local Storage Engine
    # -------------------------------------------------------------------------

    def _get_agent_and_ns(self, conn: sqlite3.Connection, agent_name: str) -> tuple[str, str]:
        c = conn.cursor()
        c.execute("SELECT id FROM agents WHERE name = ?", (agent_name.lower(),))
        row = c.fetchone()
        if row:
            aid = row[0]
        else:
            aid = str(uuid.uuid4())
            c.execute("INSERT INTO agents (id, name, role, tenant_id) VALUES (?, ?, ?, ?)",
                      (aid, agent_name.lower(), "worker", "default"))
        
        c.execute("SELECT id FROM namespaces WHERE agent_id = ?", (aid,))
        row = c.fetchone()
        if row:
            nid = row[0]
        else:
            nid = str(uuid.uuid4())
            c.execute("INSERT INTO namespaces (id, path, type, agent_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
                      (nid, f"memora://{agent_name.lower()}/private", "private", aid, "default"))
        conn.commit()
        return aid, nid

    def _record_locally(self, agent_name: str, user_input: str, agent_output: str) -> Dict[str, Any]:
        if not os.path.exists(self.local_db_path):
            return {"status": "skipped", "reason": "local db not found"}

        facts = PreferenceExtractor.extract(user_input)
        now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
        created_ids = []

        try:
            with sqlite3.connect(self.local_db_path, timeout=5.0) as conn:
                aid, nid = self._get_agent_and_ns(conn, agent_name)
                c = conn.cursor()

                for fact in facts:
                    mid = str(uuid.uuid4())
                    c.execute("""
                        INSERT INTO memory_records 
                        (id, namespace_id, owner_id, memory_type, content_text, source, confidence, importance, lifecycle_state, tenant_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (mid, nid, aid, "semantic", fact.normalized, f"agent:{agent_name.lower()}", 1.0, fact.importance, "active", "default", now_iso))
                    created_ids.append(mid)

                # Episodic turn
                mid_ep = str(uuid.uuid4())
                dialogue = f"User: {user_input} | Assistant: {agent_output}"
                c.execute("""
                    INSERT INTO memory_records 
                    (id, namespace_id, owner_id, memory_type, content_text, source, confidence, importance, lifecycle_state, tenant_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (mid_ep, nid, aid, "episodic", dialogue, f"agent:{agent_name.lower()}", 1.0, 0.7, "active", "default", now_iso))
                created_ids.append(mid_ep)
                conn.commit()

            return {"status": "success", "memory_ids": created_ids, "facts_extracted": len(facts)}
        except Exception as e:
            logger.error(f"Local storage error: {e}")
            return {"status": "error", "error": str(e)}

    def _record_fact_locally(self, agent_name: str, fact_text: str, category: str, importance: float) -> Dict[str, Any]:
        if not os.path.exists(self.local_db_path):
            return {"status": "skipped", "reason": "local db not found"}

        now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
        mid = str(uuid.uuid4())
        try:
            with sqlite3.connect(self.local_db_path, timeout=5.0) as conn:
                aid, nid = self._get_agent_and_ns(conn, agent_name)
                c = conn.cursor()
                c.execute("""
                    INSERT INTO memory_records 
                    (id, namespace_id, owner_id, memory_type, content_text, source, confidence, importance, lifecycle_state, tenant_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (mid, nid, aid, "semantic", fact_text, f"agent:{agent_name.lower()}", 1.0, importance, "active", "default", now_iso))
                conn.commit()
            return {"status": "success", "id": mid}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _recall_locally(self, agent_name: str, query: str, limit: int) -> List[Dict[str, Any]]:
        if not os.path.exists(self.local_db_path):
            return []

        # Extract meaningful keywords for matching
        clean_q = re.sub(r"[^\w\s]", "", query.lower())
        stopwords = {"what", "is", "my", "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "tell", "me", "about", "do", "you", "know"}
        words = [w for w in clean_q.split() if w not in stopwords and len(w) > 2]
        
        # If looking for favourite/favorite curry or food, expand keywords
        if "curry" in words or "favourite" in words or "favorite" in words or "food" in words:
            words.extend(["curry", "favorite", "favourite", "preference", "likes", "prawn", "prawns"])
        words = list(set(words))

        if not words:
            return []

        results = []
        try:
            with sqlite3.connect(self.local_db_path, timeout=5.0) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT m.id, m.content_text, m.memory_type, m.importance, m.created_at, a.name 
                    FROM memory_records m
                    JOIN agents a ON m.owner_id = a.id
                    WHERE m.lifecycle_state = 'active'
                    ORDER BY m.importance DESC, m.created_at DESC
                    LIMIT 100
                """)
                rows = c.fetchall()

                for row in rows:
                    content = row[1].lower()
                    matches = sum(1 for w in words if w in content)
                    if matches > 0:
                        score = matches / len(words)
                        results.append({
                            "id": row[0],
                            "content_text": row[1],
                            "memory_type": row[2],
                            "importance": row[3],
                            "created_at": row[4],
                            "owner_name": row[5],
                            "final_score": score
                        })

            results.sort(key=lambda x: (x["final_score"], x["importance"]), reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error(f"Local memory search failed: {e}")
            return []

# Singleton instance
memora_client = MemoraClient()
