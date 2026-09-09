---
description: Hunt for silent failure modes in a plan before implementing it
---

Take the plan you proposed, or the one we agreed on. Before implementing **any** of it:

1. Invoke the `skeptic` agent — but point it at the **plan**, not at code. Give it the
   plan and ask: if this plan is implemented, which step could run without error and
   still produce a wrong result?

2. Read `.claude/skills/failure-modes/SKILL.md` and walk its entries one at a time,
   stating for each whether it applies to this plan and how.

3. For each step of the plan, answer:
   - **PRE-MORTEM:** it is six months from now and this step produced wrong numbers.
     What happened?
   - Which errors here are **silent** — wrong output, no error message?
   - What invariant does this step assert about its own output? If none, that is a
     finding.
   - What does reversing this step cost?

Report the findings as a ranked list, then revise the plan against them. Do not begin
implementation until the revised plan is stated.

Anything new this turns up goes into `.claude/skills/failure-modes/SKILL.md` as part
of the work, not afterwards.
