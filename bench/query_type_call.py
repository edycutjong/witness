"""What `QueryResult.query_type` says about a read-only `CALL { }` subquery, on whatever relate-db the interpreter has.

Witness admits a query only when Relate reports it as a read (`query_type` "r"). This script asks three statements of an
in-memory store holding one node, and prints the type Relate reports for each: a plain read, a read-only `CALL { }`
subquery, and a write. It also says whether this release has a statement timeout on `Database` (1.4.0 added one). It
imports nothing from Witness, so it runs under any release:

    for v in 1.0.1 1.3.0 1.4.0; do
      uv run --no-project --with relate-db==$v python bench/query_type_call.py
    done > evidence/query-type-call.jsonl
"""

from __future__ import annotations

import json
import os
import platform

os.environ.setdefault("DO_NOT_TRACK", "1")
import relate  # noqa: E402

STATEMENTS = {
    "plain read": "MATCH (a:Airport) RETURN count(a) AS n",
    "read-only CALL subquery": "CALL { MATCH (a:Airport) RETURN count(a) AS n } RETURN n",
    "write": "CREATE (:Airport {iata: 'ZZZ'}) RETURN 1 AS n",
}


def main() -> None:
    db = relate.Database(":memory:")
    db.execute("CREATE (:Airport {iata: 'MEX'})")
    out: dict = {"relate_db": relate.__version__, "database_has_statement_timeout": hasattr(db, "statement_timeout")}
    for name, text in STATEMENTS.items():
        res = db.execute(text)
        out[name] = {"statement": text, "query_type": res.query_type, "rows": res.data}
    out["machine"] = f"{platform.system()} {platform.machine()}"
    out["python"] = platform.python_version()
    print(json.dumps(out))


if __name__ == "__main__":
    main()
