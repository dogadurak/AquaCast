# AquaCast

Basin-scale drought forecasting for the Konya Closed Basin, with honest skill
reporting.

See `PROJECT_SPEC.md` for the design, `CLAUDE.md` for the working rules, and
`AGENT_WORKFLOW.md` for how the project is built with coding agents.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
earthengine authenticate
make check          # verify every dataset is reachable
```

## Status

Phase 0 - feasibility spike. No skill claims yet.

Results will be published here only alongside the baselines they beat and by how
much. A metric without its baseline is not a result.
