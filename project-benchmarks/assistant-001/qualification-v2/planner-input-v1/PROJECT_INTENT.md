# ASSISTANT-001 — Persistent Event Journal

## Objective
Build a usable, local Python event journal for the future Assistant. Preserve
observations as evidence, expose bounded history and deterministic current state,
and survive application restarts. Deliver a library plus a small command-line
interface, not a web service, dashboard, or AI agent.

The first producers will be simulators. Later Observer and Home Assistant adapters
can use this API. This benchmark must not connect to cameras, Home Assistant,
Knowledge Core, production databases, or notification services. It does not
replace those systems or decide what the Assistant should do.

## Released benchmark decisions
CONTRACT.md is the normative API and behavioral specification. Its choices
(global IDs, source-separated state, 300-second default TTL, explicit replay
clock, and no stale-state resurrection) are NEW benchmark-v1 decisions, not claims
about an already approved production Assistant protocol. Integration/promotion
requires owner review. Every assessed rule is disclosed in that contract.

## Success
An independently launchable standard-library Python package using a real SQLite
file, with correct validation, idempotency, transaction boundaries, restart
recovery, deterministic history/state, CLI errors, and useful documentation.
A statement that tests passed is not execution evidence. Test results do not by
themselves establish maintainability, safe deployment, or role qualification.

## Scope
Python 3.10+; standard library only; no pip installation, network access, model
calls, background service, GUI, web framework, real household data, biometric
identification, or actuator control. Use only disposable files created for the
trial. No production changes, automatic promotion, or benchmark-engine edits.
