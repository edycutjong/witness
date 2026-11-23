"""Every refusal a judge can trigger from the CLI: a one-line reason, exit 2, nothing written."""

import json

import pytest

from witness.cli import main

NAMES = "MATCH (a:P)-[:R]->(b:P) RETURN DISTINCT b.name AS n ORDER BY n"


def run(tmp_path, capsys, query, *extra, store=None):
    q = tmp_path / "q.cypher"
    q.write_text(query)
    out = tmp_path / "out"
    args = ["why", "-f", str(q), "--out", str(out), "--no-cli", *extra]
    if store is not None:
        args += ["--store", str(store)]
    rc = main(args)
    err = capsys.readouterr().err
    return rc, err, out


@pytest.mark.parametrize(
    "query, door, reason",
    [
        ("MATCH (a:P) SET a.x = 1 RETURN a.name AS n", "query", "write keyword SET"),
        ("MATCH (a:P) CREATE (:P {name: 'z'}) RETURN a.name AS n", "query", "write keyword CREATE"),
        ("MATCH (a:P) RETURN rand() AS r", "query", "rand() is random"),
        ("MATCH (a:P) RETURN a.name AS n, randomUUID() AS u", "query", "random"),
        ("MATCH (a:Nothing) RETURN a.name AS n", "query", "the answer is empty"),
        ("MATCH (a:P RETURN a", "query", "Relate could not plan it"),
    ],
)
def test_refused_with_a_reason_and_nothing_written(tiny_rl, tmp_path, capsys, query, door, reason):
    rc, err, out = run(tmp_path, capsys, query, store=tiny_rl)
    assert rc == 2
    assert err.startswith(f"refused ({door}): ") and reason in err, err
    assert not out.exists() or not any(out.iterdir())


def test_store_missing(tmp_path, capsys):
    rc, err, _ = run(tmp_path, capsys, NAMES, store=tmp_path / "nope.rl")
    assert rc == 2 and "refused (store): store not found" in err


def test_query_file_missing(tiny_rl, tmp_path, capsys):
    rc = main(["why", "-f", str(tmp_path / "gone.cypher"), "--store", str(tiny_rl), "--no-cli"])
    assert rc == 2 and "query file not found" in capsys.readouterr().err


def test_differs_needs_an_expected_answer(tiny_rl, tmp_path, capsys):
    rc, err, _ = run(tmp_path, capsys, NAMES, "--predicate", "differs", store=tiny_rl)
    assert rc == 2 and "differs needs --expected" in err


def test_timeout_is_inconclusive_never_verified(tiny_rl, tmp_path, capsys):
    slow = (
        "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) WITH collect(h.name) AS hubs "
        "UNWIND range(1, 3000000) AS i WITH hubs, sum(i) AS s RETURN hubs, s"
    )  # ~1 s per run: every trial overruns the 0.2 s watchdog
    q = tmp_path / "slow.cypher"
    q.write_text(slow)
    rc = main(
        [
            "why",
            "-f",
            str(q),
            "--store",
            str(tiny_rl),
            "--out",
            str(tmp_path / "o"),
            "--no-cli",
            "--isolate",
            "--trial-timeout",
            "0.2",
            "--max-trials",
            "2",
        ]
    )
    out = capsys.readouterr().out
    man = json.loads((tmp_path / "o" / "slow.manifest.json").read_text())
    assert rc != 0 and "NOT verified" in out
    assert man["verified"] is False and man["run"]["inconclusive"] == 2 and man["determinism_claimed"] is False
