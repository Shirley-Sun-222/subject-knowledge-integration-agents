from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db import connect, init_db


def filename_stem(filename: str) -> str:
    return Path(filename).stem


def delete_textbooks(textbook_ids: list[str]) -> int:
    if not textbook_ids:
        return 0
    placeholders = ",".join("?" for _ in textbook_ids)
    with connect() as conn:
        conn.execute(f"DELETE FROM chunks WHERE textbook_id IN ({placeholders})", textbook_ids)
        conn.execute(f"DELETE FROM knowledge_edges WHERE textbook_id IN ({placeholders})", textbook_ids)
        conn.execute(f"DELETE FROM knowledge_nodes WHERE textbook_id IN ({placeholders})", textbook_ids)
        conn.execute(f"DELETE FROM chapters WHERE textbook_id IN ({placeholders})", textbook_ids)
        conn.execute(f"DELETE FROM textbooks WHERE id IN ({placeholders})", textbook_ids)
        conn.execute("DELETE FROM integration_decisions")
    return len(textbook_ids)


def repair_titles() -> int:
    changed = 0
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, title FROM textbooks WHERE title LIKE 'book_%' AND filename IS NOT NULL AND filename != ''"
        ).fetchall()
        for row in rows:
            title = filename_stem(row["filename"])
            conn.execute("UPDATE textbooks SET title = ? WHERE id = ?", (title, row["id"]))
            changed += 1
    return changed


def delete_algorithm_fixtures() -> int:
    with connect() as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM textbooks WHERE filename = '算法.md'")]
    return delete_textbooks(ids)


def clear_derived_data() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM knowledge_edges")
        conn.execute("DELETE FROM knowledge_nodes")
        conn.execute("DELETE FROM integration_decisions")
        conn.execute("DELETE FROM dialogue_messages")
        conn.execute("DELETE FROM metrics")


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair or clean local runtime data without touching uploaded files.")
    parser.add_argument("--repair-titles", action="store_true", help="Replace book_xxx titles with the original filename stem.")
    parser.add_argument("--delete-algorithm-fixtures", action="store_true", help="Remove local 算法.md fixture textbooks and dependent data.")
    parser.add_argument("--clear-derived", action="store_true", help="Clear graph/RAG/integration derived data so samples can be rebuilt cleanly.")
    args = parser.parse_args()

    init_db()
    changed_titles = repair_titles() if args.repair_titles else 0
    deleted_fixtures = delete_algorithm_fixtures() if args.delete_algorithm_fixtures else 0
    if args.clear_derived:
        clear_derived_data()

    print(
        {
            "repaired_titles": changed_titles,
            "deleted_algorithm_fixtures": deleted_fixtures,
            "cleared_derived": bool(args.clear_derived),
        }
    )


if __name__ == "__main__":
    main()
