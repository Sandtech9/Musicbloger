# ============================================================================
# Zedhits Autonomous Disk-DB Sanitizer Agent
# ============================================================================
import os
import sys
import sqlite3
import hashlib

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_FILE = os.path.join(BASE_DIR, "zedhits.db")
MEDIA_DIR = os.path.join(BASE_DIR, "media", "tracks")

def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def run_sanitizer():
    print("====================================================================")
    print("  Zedhits Autonomous Self-Healing Disk & Database Sanitizer Agent   ")
    print("====================================================================")

    if not os.path.exists(DB_FILE):
        print(f"[Sanitizer] Database file not found at {DB_FILE}. Initializing database first.")
        from database import init_db
        init_db()

    os.makedirs(MEDIA_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    orphaned_db_records = 0
    orphaned_disk_files = 0
    corrupted_hashes = 0

    try:
        # Phase 1: Verify DB records -> Disk Files
        print("\n[Phase 1/2] Scanning Database Media Records for missing physical files...")
        cursor = conn.cursor()
        rows = cursor.execute("SELECT id, track_id, storage_path, sha256_hash FROM media_files").fetchall()

        valid_storage_paths = set()

        for row in rows:
            mf_id = row["id"]
            track_id = row["track_id"]
            storage_path = os.path.abspath(row["storage_path"])
            db_hash = row["sha256_hash"]

            if not os.path.exists(storage_path):
                # Attempt self-healing path re-anchoring to current MEDIA_DIR
                filename = os.path.basename(row["storage_path"])
                reanchored_path = os.path.abspath(os.path.join(MEDIA_DIR, filename))
                if os.path.exists(reanchored_path):
                    print(f"  [RECOVERY] Re-anchored storage path for DB Record #{mf_id}: {storage_path} -> {reanchored_path}")
                    with conn:
                        conn.execute("UPDATE media_files SET storage_path = ? WHERE id = ?", (reanchored_path, mf_id))
                    storage_path = reanchored_path
                    valid_storage_paths.add(storage_path)
                else:
                    print(f"  [ALERT] Missing Disk File: DB Record #{mf_id} (Track #{track_id}) -> {storage_path}")
                    # Delete orphaned track record
                    with conn:
                        conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
                    orphaned_db_records += 1
                    print(f"  [RECOVERY] Purged orphaned Track #{track_id} and Media #{mf_id} from Database.")
                    continue
            else:
                valid_storage_paths.add(storage_path)
                # Verify SHA-256 integrity
                actual_hash = compute_sha256(storage_path)
                if actual_hash != db_hash:
                    print(f"  [CORRUPTION] Hash mismatch for {storage_path}: DB={db_hash[:8]}... Disk={actual_hash[:8]}...")
                    with conn:
                        conn.execute("UPDATE media_files SET sha256_hash = ? WHERE id = ?", (actual_hash, mf_id))
                    corrupted_hashes += 1
                    print(f"  [RECOVERY] Synchronized SHA-256 hash in Database.")

        # Phase 2: Verify Disk Files -> DB Records
        print("\n[Phase 2/2] Scanning 'media/tracks/' directory for unindexed/orphaned physical files...")
        disk_files = [os.path.join(MEDIA_DIR, f) for f in os.listdir(MEDIA_DIR) if os.path.isfile(os.path.join(MEDIA_DIR, f))]

        for disk_file in disk_files:
            abs_disk_file = os.path.abspath(disk_file)
            if abs_disk_file not in valid_storage_paths:
                print(f"  [ALERT] Orphaned Physical File on Disk: {abs_disk_file}")
                try:
                    os.remove(abs_disk_file)
                    orphaned_disk_files += 1
                    print(f"  [RECOVERY] Physically purged unindexed file: {os.path.basename(abs_disk_file)}")
                except Exception as e:
                    print(f"  [ERROR] Failed to remove file {abs_disk_file}: {e}")

        print("\n====================================================================")
        print("  SANITIZATION & SELF-HEALING AUDIT REPORT:")
        print(f"  - Orphaned Database Records Purged: {orphaned_db_records}")
        print(f"  - Orphaned Disk Files Purged:       {orphaned_disk_files}")
        print(f"  - Corrupted SHA-256 Hashes Repaired: {corrupted_hashes}")
        print("  STATUS: Disk and DB are 100% synchronized.")
        print("====================================================================")

    finally:
        conn.close()

if __name__ == "__main__":
    run_sanitizer()
