"""--isolate: trials in a killable child process; a timeout is an inconclusive trial, never proof."""

from pathlib import Path

from witness.pipeline import Request, reduce_request

NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"


def test_isolated_trials_give_the_same_witness(tiny_rl, tmp_path):
    common = dict(source=Path(tiny_rl), statement=NAMES, params={}, ledger=None, use_cli=False)
    a = reduce_request(Request(**common, out_dir=tmp_path / "a", name="w"))
    b = reduce_request(Request(**common, out_dir=tmp_path / "b", name="w", isolate=True, trial_timeout=60))
    assert b.verified and b.run["isolate_restarts"] == 0
    assert Path(a.files["cypher"]).read_text() == Path(b.files["cypher"]).read_text()


SLOW = (
    "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) WITH collect(h.name) AS hubs "
    "UNWIND range(1, 3000000) AS i WITH hubs, sum(i) AS s RETURN hubs, s"
)  # ~1.2 s per run on an M1 Max: every trial overruns a 0.3 s timeout


def test_trial_timeout_is_inconclusive(tiny_rl, tmp_path):
    o = reduce_request(
        Request(
            source=Path(tiny_rl),
            statement=SLOW,
            params={},
            ledger=None,
            use_cli=False,
            out_dir=tmp_path / "o",
            name="w",
            isolate=True,
            trial_timeout=0.3,
            max_trials=2,
            order_check=False,
        )
    )
    assert o.run["inconclusive"] == 2 and o.run["isolate_restarts"] == 2
    trace = __import__("json").loads(Path(o.files["trace"]).read_text())
    assert all("TrialTimeout" in t["error"] and t["holds"] is None for t in trace["trials"])
    assert o.manifest["determinism_claimed"] is False
    assert o.exit_code != 0  # an inconclusive trial deletes nothing, so W is never claimed deletion-minimal
