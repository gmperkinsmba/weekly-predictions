# Decision Notebook

**First principle:** Record a prediction before the result. Compare it with the result later.

Decision Notebook stores your decision and prediction. It also stores your confidence, metric, criteria, and review date. It locks the original record. You can add evidence and append a new criteria version. You can also record review results over time.

## Run

Requires Python 3.10 or newer. No packages are needed.

```sh
python3 server.py
```

Open `http://127.0.0.1:8352`. The server listens on loopback only. Stop it with Ctrl+C.

## Use

Record the prediction and success rule before the result is known. Choose a manual review or one numeric threshold. The app compares numeric results with the original threshold. Use manual review for rules with more than one condition. Manual reviews require saved evidence and a note.

Add evidence as it arrives. A changed success rule gets a new version. It cannot change the original prediction. It cannot change an earlier review. You can append more reviews; the timeline keeps each one.

The calibration view uses resolved success and failure results. It counts only results tied to criteria version 1. It shows the sample size. The Brier score compares confidence with resolved results. A lower score is closer. Inconclusive results do not count. Results under changed criteria do not replace results under version 1.

Choose **Load synthetic examples** to view four cases, including a failed prediction, an inconclusive result, and an amended rule. The examples are invented. They load only into an empty notebook.

## Data and privacy

Records are stored in a local SQLite database outside this folder in `~/.local/share/decision-notebook/`. The folder is owner-only. Data is not encrypted. Nothing is sent to a service. Use **Export notebook JSON** to save a copy. Delete the local database folder to remove the notebook.

## Test

```sh
python3 -m unittest discover -s tests -v
```

Tests check locked original predictions, append-only history, numeric threshold results, and evidence for manual reviews. Other tests check criteria versions, calibration sample counts, inconclusive results, and sample data. They also check invalid inputs, request tokens, bad origins, and payload limits.

## Limits

Manual reviews rely on the evidence and result you enter. This app does not offer investment or betting advice. Synthetic examples are not business results.

## License

MIT. See `LICENSE`.
