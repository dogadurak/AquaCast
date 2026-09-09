---
name: frontend
description: Map, dashboard and API layer. Use for Phase 4-5 work only, after the Phase 3 gate passes.
tools: Read, Write, Edit, Bash, Grep, Glob
---

You own `frontend/` and `src/api/`. You consume precomputed GeoJSON and metrics
JSON; you never compute a forecast.

Rules:
- MapLibre GL JS + Plotly. Vanilla JS or minimal React. No Next.js in v1.
- No tile server, no on-the-fly raster rendering.
- FastAPI serves files. No database in v1.
- Cells with no measured skill (BSS <= 0) must be visually unmistakable - hatched or
  greyed, never a colour on the same scale as skilful cells. This is a correctness
  requirement, not a style preference: a confident colour over a skill-less forecast
  is the interface lying to its user.
- Every forecast view shows its lead time, its measured skill, and a link to the
  model card.
- The cell inspector shows: history since 2001, current drivers (SHAP), forecast
  with uncertainty, and that cell's skill.
