"""Start the local study app or export its event data to a local JSON file."""

import argparse
import json
from pathlib import Path

from .app import create_app
from .backends import TOP_K
from .study import SETUPS, Study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", choices=SETUPS, default="paired")
    parser.add_argument("--rehearsal", action="store_true", help="Use labeled fixture suggestions and no recommender calls.")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--port", type=int, default=8060)
    parser.add_argument("--export", type=Path, metavar="OUTPUT_JSON")
    args = parser.parse_args()
    db = args.db or Path("data/evaluation_app/rehearsal.sqlite" if args.rehearsal
                         else "data/evaluation_app/study.sqlite")
    if args.export:
        if not db.is_file():
            parser.error(f"Database does not exist: {db}")
        study = Study(db)
        with study.connect() as conn:
            data = {}
            for table in ("sessions", "playlist", "rounds", "panels", "offers", "checkpoints"):
                records = []
                for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                    record = dict(row)
                    for key in ("track", "arms"):
                        if key in record:
                            record[key] = json.loads(record[key])
                    records.append(record)
                data[table] = records
            summary = conn.execute(
                """WITH panel_counts AS (
                       SELECT r.session_id, p.round_id, p.arm, p.status,
                              count(o.rank) AS shown, sum(o.decision IS 'keep') AS kept
                       FROM rounds r JOIN panels p ON p.round_id = r.id
                       LEFT JOIN offers o ON o.round_id = p.round_id AND o.position = p.position
                       GROUP BY p.round_id, p.position
                   ), paired_rounds AS (
                       SELECT round_id FROM panel_counts GROUP BY round_id
                       HAVING count(*) = 2 AND sum(status = 'ok') = 2
                   )
                   SELECT session_id, arm, sum(shown) AS shown, sum(kept) AS kept,
                          1.0 * sum(kept) / nullif(sum(shown), 0) AS keep_rate,
                          sum(CASE WHEN status = 'ok' THEN ? - shown ELSE 0 END) AS empty_slots,
                          sum(status = 'unavailable') AS failed_panels,
                          sum(status = 'not_applicable') AS not_applicable_panels,
                          coalesce(sum(shown) FILTER (WHERE paired.round_id IS NOT NULL), 0) AS paired_shown,
                          coalesce(sum(kept) FILTER (WHERE paired.round_id IS NOT NULL), 0) AS paired_kept,
                          1.0 * sum(kept) FILTER (WHERE paired.round_id IS NOT NULL)
                              / nullif(sum(shown) FILTER (WHERE paired.round_id IS NOT NULL), 0) AS paired_keep_rate
                   FROM panel_counts LEFT JOIN paired_rounds AS paired USING (round_id)
                   GROUP BY session_id, arm ORDER BY session_id, arm""", (TOP_K,),
            )
            data["participant_arm_summary"] = [dict(row) for row in summary]
        args.export.parent.mkdir(parents=True, exist_ok=True)
        with args.export.open("x", encoding="utf-8") as output:
            args.export.chmod(0o600)
            json.dump(data, output, ensure_ascii=False, indent=2)
        return
    create_app(db, setup=args.setup, rehearsal=args.rehearsal).run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
