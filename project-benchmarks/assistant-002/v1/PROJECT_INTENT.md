# ASSISTANT-002 — Event Simulator and Replay

Build a usable offline simulator for Assistant observations, not another journal.
It must turn a declared scenario into deterministic deliveries, drive an injected
journal through a virtual clock, compare observations against declared expectations,
and resume from a checkpoint without inventing missing events or losing evidence.

Useful questions include: what happens after a sensor reconnects and sends the
same event again? Can a late observation displace a newer one? Does expired
presence become unknown? Does replay recover when a write succeeds but saving
progress does not? No live cameras, Home Assistant, Knowledge Core, notifications,
actuators, network access or language-model reasoning belong in this component.

Deliver a Python 3.10+ standard-library package and CLI. The journal is a supplied
interface, not a component to reimplement. A frozen event-validation helper is
provided so this test measures simulation and recovery rather than rebuilding R01.
Its provenance is declared in UPSTREAM.json. This helper is calibration-derived,
not evidence that a candidate model has completed Assistant-001.

CONTRACT.md contains every assessed rule. Defaults, fault transforms and checkpoint
format are new benchmark-v1 decisions, not an already deployed Assistant protocol.
Only candidate acceptance plus human review and owner approval can promote code.
The six-task fixed-plan Worker chain is not the full autonomous five-role pipeline.
