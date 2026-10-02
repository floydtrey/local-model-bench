# Tester Qualification Plan

Date: 2026-10-02

## Purpose

Tester qualification is separate from Worker qualification.

An unqualified Tester must not become the judge used to select an unqualified Worker. Each role is measured independently first; integrated Worker-to-Tester loops are evaluated only after both roles have qualified candidates.

## Tester contract

The Tester must be able to:

1. determine whether adequate verification already exists;
2. reuse existing tests when they are sufficient;
3. create a focused missing test when necessary;
4. run tests through deterministic tooling;
5. distinguish a bad test from a real implementation defect;
6. repair and retry a bad test;
7. distinguish runtime/infrastructure failure from implementation failure;
8. return useful bounded repair criteria for a real Worker defect;
9. avoid modifying production code;
10. avoid expanding into unrelated or later tasks.

The deterministic test runner remains the source of execution evidence. The Tester model selects, creates, and interprets tests; it does not manufacture pass/fail evidence by assertion.

## Qualification corpus

Build frozen cases with known ground truth.

### Case A — correct implementation, adequate existing test

Fixture:
- Worker implementation is correct.
- Existing project tests already verify the assigned behavior.

Expected Tester behavior:
- identify the adequate existing test;
- run it;
- avoid writing duplicate tests;
- return PASS.

Failure signals:
- unnecessary test creation;
- production-code modification;
- false FAIL.

### Case B — correct implementation, missing coverage

Fixture:
- Worker implementation is correct.
- Existing tests do not verify one required behavior.

Expected Tester behavior:
- identify the coverage gap;
- add the minimum focused test;
- run it successfully;
- return PASS.

Failure signals:
- claims existing tests are sufficient when they are not;
- creates broad/unrelated test infrastructure;
- writes production code.

### Case C — defective implementation, weak existing tests

Fixture:
- Worker implementation contains a known requirement defect.
- Existing tests all pass because coverage is incomplete.

Expected Tester behavior:
- identify the missing verification;
- add a targeted test;
- expose the known defect;
- return FAIL with repair criteria tied to the requirement.

Failure signals:
- returns PASS because old tests pass;
- test does not actually expose the defect;
- provides unrelated repair advice.

### Case D — correct implementation, bad newly written test

Fixture:
- Worker implementation is correct.
- A candidate test is deliberately incorrect and fails.

Expected Tester behavior:
- diagnose the test as invalid;
- repair or replace the test;
- rerun;
- return PASS when valid evidence succeeds.

Failure signals:
- blames the Worker for the bad test;
- deletes/weakens the test without replacing it with valid verification;
- returns PASS without rerunning valid evidence.

The original Qwen3.8 Intent 04 Task 4 artifact may be useful as a real-world seed for this case after its exact failing assertion is reviewed and classified.

### Case E — defective implementation, valid failing test

Fixture:
- Worker implementation is wrong.
- A valid existing or supplied test exposes the defect.

Expected Tester behavior:
- confirm the test matches the requirement;
- return FAIL;
- provide concise repair criteria;
- do not edit production code.

Failure signals:
- rewrites a valid test to make the implementation pass;
- produces an implementation patch itself;
- misstates the acceptance criterion.

### Case F — runtime/infrastructure failure

Fixture:
- implementation correctness is not the source of failure;
- test execution is interrupted by a known runtime/tool/environment problem.

Expected Tester behavior:
- return BLOCKED;
- identify the concrete infrastructure problem;
- do not classify the Worker as failing.

Failure signals:
- invents implementation repair criteria;
- treats runtime failure as test evidence.

## Deterministic scoring

Each Tester case should have benchmark-owned expected facts:

- whether adequate existing coverage exists;
- whether test creation is required;
- allowed test paths;
- ground-truth implementation status;
- required test behavior;
- whether the expected final result is PASS, FAIL, or BLOCKED;
- required repair-criterion anchors for FAIL cases;
- forbidden production paths.

Score separately:

- coverage decision;
- test scope;
- test validity;
- deterministic execution result;
- bad-test diagnosis;
- runtime-failure diagnosis;
- final classification;
- repair-criteria quality;
- production-code restraint;
- efficiency / unnecessary test creation.

## Integrated phase

After Worker and Tester finalists are known, run a separate integration benchmark:

Worker attempt -> Tester -> deterministic test execution -> Tester diagnosis -> Worker repair -> Tester retest.

That benchmark measures pipeline reliability, not isolated role quality.

Do not use gold recovery in the integrated phase. Real failures should propagate naturally so the interaction itself is measured.
