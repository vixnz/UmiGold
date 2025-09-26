from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import sqlite3
import os
import json
import hashlib
from typing import Dict, Any
import logging

logging.basicConfig(filename='telemetry.log', level=logging.INFO)

class TelemetryDB:
    def __init__(self, db_path=":memory:", key_path="telemetry.key"):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_table()
        self.key = self._load_or_generate_key(key_path)

    def _load_or_generate_key(self, key_path: str) -> bytes:
        """Load AES key from disk, generate if not present"""
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                return f.read()
        key = os.urandom(32)  # 256-bit
        with open(key_path, "wb") as f:
            f.write(key)
        return key

    def _create_table(self):
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT NOT NULL,       -- e.g., 'ACCEPTED', 'IGNORED'
            suggestion_id TEXT NOT NULL,
            encrypted_payload BLOB NOT NULL,
            anonymized_user_id TEXT NOT NULL,
            metadata TEXT
        )
        """)
        self.conn.commit()

    def _generate_user_id(self) -> str:
        """Anonymized user ID (8 hex chars)"""
        rand_bytes = os.urandom(16)
        return hashlib.sha256(rand_bytes).hexdigest()[:8]

    def encrypt_payload(self, payload: Dict[str, Any]) -> bytes:
        """AES-GCM encryption with automatic IV handling"""
        iv = os.urandom(12)
        aesgcm = AESGCM(self.key)
        plaintext = json.dumps(payload).encode()
        ciphertext = aesgcm.encrypt(iv, plaintext, None)
        return iv + ciphertext

    def decrypt_payload(self, encrypted: bytes) -> Dict[str, Any]:
        """AES-GCM decryption"""
        iv, ciphertext = encrypted[:12], encrypted[12:]
        aesgcm = AESGCM(self.key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return json.loads(plaintext.decode())

    def record_interaction(self, event_type: str, suggestion_id: str,
                           context_embedding: bytes, metadata: Dict[str, Any] = None):
        """Store encrypted interaction record"""
        try:
            payload = {
                "event": event_type,
                "suggestion_id": suggestion_id,
                "context_sha256": hashlib.sha256(context_embedding).hexdigest()[:16]
            }
            encrypted = self.encrypt_payload(payload)
            user_id = self._generate_user_id()
            self.cursor.execute(
                "INSERT INTO interactions (event_type, suggestion_id, encrypted_payload, anonymized_user_id, metadata) VALUES (?, ?, ?, ?, ?)",
                (event_type, suggestion_id, encrypted, user_id, json.dumps(metadata or {}))
            )
            self.conn.commit()
        except Exception as e:
            logging.error(f"Telemetry failed: {e}")

    def get_adaptation_data(self) -> Dict[str, float]:
        """Compute acceptance ratios for reinforcement learning"""
        self.cursor.execute("""
        SELECT suggestion_id, 
               SUM(CASE WHEN event_type='ACCEPTED' THEN 1 ELSE 0 END) AS accepts,
               COUNT(*) AS total
        FROM interactions
        GROUP BY suggestion_id
        """)
        return {row[0]: row[1] / row[2] for row in self.cursor.fetchall()}

# Example usage
if __name__ == "__main__":
    db = TelemetryDB("telemetry.sqlite")
    fake_embedding = os.urandom(768)
    db.record_interaction("REJECTED", "loop-opt-001", fake_embedding, {"lang": "python"})
    db.record_interaction("ACCEPTED", "loop-opt-001", fake_embedding, {"lang": "python"})

    print("Adaptation ratios:", db.get_adaptation_data())

    # Retrieve & decrypt one record (demo)
    db.cursor.execute("SELECT encrypted_payload FROM interactions LIMIT 1")
    encrypted_payload = db.cursor.fetchone()[0]
    print("Decrypted payload:", db.decrypt_payload(encrypted_payload))
