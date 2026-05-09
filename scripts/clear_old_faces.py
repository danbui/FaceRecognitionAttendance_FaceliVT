import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "attendance.db"

def main():
    if not DB_PATH.exists():
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check how many we are deleting
        cursor.execute("SELECT COUNT(*) FROM face_embeddings")
        count = cursor.fetchone()[0]
        
        # Delete old embeddings
        cursor.execute("DELETE FROM face_embeddings")
        conn.commit()
        
        print(f"✅ Successfully deleted {count} old face embeddings (128-dim).")
        print("You can now enroll new faces with the 512-dim FaceLiVT model.")
    except Exception as e:
        print("Error:", e)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
