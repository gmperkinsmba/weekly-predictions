# Context

## Decision

A choice recorded before its result. Its title, question, prediction, confidence, metric, original success criteria, metric rule, and review date do not change.

## Evidence

A dated note attached after a decision is recorded. Evidence entries remain in the event history.

## Criteria version

Version 1 is the original success rule. A later rule is appended with a higher version. Later versions cannot change version 1 or its calibration result.

## Outcome

A dated review tied to the criteria version in effect at the time. Numeric outcomes compare an observed number with the original threshold. Manual outcomes need evidence and a note. Inconclusive outcomes are excluded from calibration.

## Calibration

Counts the latest resolved binary outcome tied to criteria version 1 for each decision. Shows eligible sample size. Amended criteria and inconclusive results do not count.

## Local store

SQLite holds original decision records and append-only event rows outside the app folder. IDs are strings. JSON export is user initiated.
