"""Read-only local PostgreSQL extraction; raw data is never committed.

Use MRANKED_RESEARCH_DATABASE_URL for a disposable/restored loopback database.
No Docker command or shell is built from command-line input.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict


def local_parameters(dsn):
    params = conninfo_to_dict(dsn)
    hosts = {"localhost": "127.0.0.1", "127.0.0.1": "127.0.0.1", "::1": "::1"}
    host = params.get("host")
    if host not in hosts or params.get("service") or params.get("hostaddr", hosts[host]) != hosts[host]:
        raise ValueError("research export requires an explicit loopback database")
    # Pin the address too: a host name or ambient PGHOSTADDR cannot redirect it.
    params["hostaddr"] = hosts[host]
    return params


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get("MRANKED_RESEARCH_DATABASE_URL", "")
    if not dsn:
        parser.error("MRANKED_RESEARCH_DATABASE_URL is required")
    params = local_parameters(dsn)
    sql = Path(__file__).resolve().parents[1] / "sql/observable_panel.sql"
    source = sql.read_bytes()
    text = source.decode()
    # The checked-in query is the only query this helper runs.
    query = text[text.index("COPY ("):text.index(") TO STDOUT;") + len(") TO STDOUT;")]
    rows = []
    with psycopg.connect(**params) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '120s'")
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        with connection.cursor().copy(query) as copy:
            for row in copy.rows():
                line = row[0].encode()
                json.loads(line)
                rows.append(line)
    payload = b"\n".join(rows) + b"\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as output:
            output.write(payload)
    print(json.dumps({"posts": len(rows), "uncompressed_sha256": hashlib.sha256(payload).hexdigest(),
                      "sql_sha256": hashlib.sha256(source).hexdigest()}))


if __name__ == "__main__":
    main()
