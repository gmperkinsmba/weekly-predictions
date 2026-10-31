# Context

## Weekly prediction

A weekly prediction is written for an upcoming Monday-to-Sunday period. The app records the user's prediction, check method, confidence, and success rule before the period begins. Saving makes those original values immutable. The app asks the user to confirm they wrote the prediction without AI assistance, but cannot verify the claim.

## Weekly review

After Sunday, the user appends observed evidence, chooses Right, Missed, or Not clear yet, and records a lesson for next week. Reviews are append-only. Unresolved and unclear weeks are not failures.

## Weekly scores

Weekly scores use only resolved weekly predictions. They exclude synthetic examples and legacy non-weekly rows. The summary reports resolved count, average confidence, actual right rate, and confidence-minus-right-rate gap in percentage points. Positive means confidence was higher than the right rate. Small samples warrant caution.

## Earlier Decision Notebook records

Older decision rows remain readable with their original IDs, immutable prediction fields, evidence, criteria versions, outcomes, and calibration history. They do not contribute to weekly scores. Existing runtime path and bundle identifier remain stable for data continuity.

## Local store

SQLite stores records and append-only events outside the app folder at the existing `~/.local/share/decision-notebook/` path. IDs are strings. JSON export is user initiated. No account, LLM, or external service is used.
