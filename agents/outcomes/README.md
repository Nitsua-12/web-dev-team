# Outcome Feedback Loop

There's no automated way to know a deal closed — that only happens in a
real conversation, after a human takes over per the Sales Handoff
Dossier. This is where that final result gets recorded, and where it
feeds back into the Dossier agent's estimates.

No API keys, no pip dependencies beyond the stdlib.

## An honest note on scope

As of building this, **zero real outreach has been sent** anywhere in
this pipeline — everything so far has been drafts, demos, and tests.
That means this agent's statistical value is currently zero, and
pretending otherwise would mean fabricating calibration from an empty
dataset — exactly the kind of fake-precise confidence this whole project
has deliberately avoided (see the Dossier agent's own "no fake-precise
numbers" rule). What's built here is the **infrastructure**: correct,
tested, and ready to become genuinely useful the moment real sends and
real outcomes start happening. Until then, every report and every
Dossier this feeds honestly says "not enough data" rather than inventing
a number.

## Running

```
python outcomes_cli.py record --business "Village Tattoo NYC" --outcome won --value 450 --notes "Signed after a call"
python outcomes_cli.py record --business "Some Shop" --outcome lost --notes "Went with a competitor"
python outcomes_cli.py record --business "Another Shop" --outcome ongoing
python outcomes_cli.py report
```

Valid `--outcome` values: `won`, `lost`, `no_response`, `ongoing`. A
lead's outcome can change over time (`ongoing` → `won`) — re-recording
updates the existing entry rather than erroring.

## What `report` shows

The real funnel across every stage this pipeline can actually measure:
sent (from [scheduler](../scheduler)) → replied (from
[reply_triage](../reply_triage)) → outcome (this agent). Every source is
optional — if a sibling agent has never been run, its database simply
doesn't exist yet, and that stage just shows zero rather than erroring.
Below 5 outcomes recorded, the report explicitly says the sample is too
small to be meaningful.

## How this feeds the Dossier agent

[generate_dossier.py](../dossier/generate_dossier.py) now computes this
same funnel once per run and includes it in the prompt — but **only**
when at least one real send exists (`total_sent > 0`); with zero data,
the section is omitted entirely rather than presented as empty or
fabricated. When real data does exist, the model is instructed to
factor it into the likelihood/budget reasoning while explicitly flagging
a small sample rather than treating a handful of data points as a
reliable rate.

## Verified without spending on a live API call

The user specifically asked for a no-cost verification pass rather than
a live Claude run, so this was tested at the level that could actually
catch bugs without spending anything:

- Loaded `generate_dossier.py` through the exact same cross-module import
  mechanism it uses at runtime, confirming `outcomes/stats.py` resolves
  correctly with no import errors.
- Called `compute_funnel()` against the real (currently empty) databases
  and confirmed `build_funnel_context()` returns an empty string — the
  zero-data case is provably not fabricated, not just assumed.
- Called `build_funnel_context()` again with synthetic in-memory data
  (6 sent, 3 replied, 2 outcomes, 1 won at $450) and confirmed both the
  real numbers and the small-sample warning appear correctly.
- Separately ran `outcomes_cli.py record` and `report` against a real
  lead (Village Tattoo NYC) to confirm the CLI and funnel computation
  work end-to-end. Test entry removed afterward.

## Known limitations

- **No live-run verification of the Dossier integration yet** — the
  static checks above prove the wiring is correct, but an actual Claude
  call incorporating this context into a real dossier hasn't been run.
  Worth doing once there's real data to test against anyway.
- **No connection to `reverify`** — if a lead's qualification status
  changes after an outcome was recorded, nothing reconciles the two.
  Unlikely to matter in practice (an outcome typically means the lead
  is no longer being actively re-verified) but not enforced. Same gap
  documented from the other side in
  [../reverify/README.md](../reverify/README.md#known-limitations).
- **`--business` requires an exact match**, same limitation as every
  other CLI in this project — use `--phone` if unsure of exact spelling.
