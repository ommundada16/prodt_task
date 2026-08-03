# Documentation of AI Coding Assistant Usage

## Summary

Claude Code (Claude Sonnet 5) was the primary AI coding assistant used
throughout this project. It was used interactively across the full build -
the supplier adapters and mock supplier APIs, the search aggregation and
ranking service, the Temporal booking workflow and its activities, the
pytest test suite, structured logging, and the Docker/docker-compose
setup - with each piece committed to git and verified before moving to the
next. The commit history is the real record of how this was built, in
order.

Antigravity was also used on this project. Where it was used, its output
was reviewed against the running system before being kept.

## How work was verified, not just generated

A recurring pattern throughout: nothing was accepted purely because the
AI wrote it and it looked reasonable. Concretely:

- The supplier adapters and mock APIs were exercised with real requests
  (search, idempotent reservation creation, forced-failure-then-retry,
  pending -> confirmed status polling) before being committed.
- The Temporal workflow was tested against Temporal's time-skipping test
  environment for logic correctness, and separately run against a real,
  Docker-hosted Temporal server to confirm it behaves the same way
  end-to-end (including a full booking reaching `confirmed` and then
  being cancelled afterward).
- Duplicate-booking prevention was checked at the database level (querying
  for actual duplicate rows), not just assumed from reading the code.
- A worker-restart-recovery test was added specifically to verify
  Temporal's core guarantee - that workflow state survives a worker
  process being torn down and replaced - rather than taking that
  guarantee on faith.
- The one-command Docker setup was validated by actually stopping every
  locally running process and bringing the whole stack up fresh with
  `docker compose up --build`, then re-running the search -> book ->
  confirm flow purely against the containerized services.

## Known rough edges caught during this process

- An early version of the workflow used `workflow.sleep`, which does not
  exist in this Temporal SDK version - caught immediately by running the
  workflow rather than assuming it worked.
- Making a confirmed booking stay cancellable required a second pass:
  the initial implementation left `GET /bookings/{id}/result` blocking
  forever on a confirmed (but no longer completing) workflow. This was
  caught by testing the change live, not by review alone, and fixed with
  a non-blocking `details()` query.
