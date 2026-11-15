# Why ddmin is sweep-and-continue (console record, 2026-11-15)

The first `bench/country_scan.py` run used a ddmin that restarted from chunk 0 after every commit. On the first scanned
candidate with 2–5 answer rows (AE/DXB, alphabetically first; its witness turned out to be 266 relationships) it stopped
in Phase A with:

```
witness.reduce.TrialCapReached: 20000
uv run python bench/country_scan.py  115.71s user 0.73s system 98% cpu 1:57.64 total
```

The crashed run wrote no row, so this console output is the only record. With the sweep-and-continue ddmin now in
`src/witness/reduce.py` (a sweep repeats while it commits; the pass ends only after a commit-free sweep at n = |C|),
the same pair reduces in 29.6 s (`country-scan.jsonl`, final scan), and the MX/MEX headline in 371 trials.
