# Weekly Predictions

**First principle:** Write next week’s predictions yourself before the week begins. Lock confidence and the success rule, then compare the prediction with observed facts and record a lesson.

Weekly Predictions is a private, local Mac app. It does not use AI to write, edit, or score predictions. It asks you to confirm that you wrote each prediction in your own words without AI help. The app cannot verify that.

## Install and run

Build on macOS with Python 3.12 or newer and `uv`. The build bundles Python, so the installed app does not need Python on your system.

```sh
uv venv --python 3.12 .desktop-venv
uv pip install --python .desktop-venv/bin/python -r requirements-desktop.lock.txt
uv run --python .desktop-venv/bin/python build_desktop.py
uv run --python .desktop-venv/bin/python install_desktop.py
```

The app installs at `~/Applications/Weekly Predictions.app`. Open it in Finder or add it to the Dock. Choose **Quit** from the app menu or press Command-Q to quit. This local build is not Developer ID signed or notarized. If macOS blocks the first launch, Control-click the app, choose **Open**, then confirm.

To uninstall, move `~/Applications/Weekly Predictions.app` to the Trash. Your notebook remains in `~/.local/share/decision-notebook/` for continuity with earlier Decision Notebook data. Remove that folder only if you want to delete all records. If install fails, the installer keeps a dated backup beside the installed app and verifies the existing bundle ID and ownership marker before replacement.

## Weekly practice

Choose an upcoming Monday-to-Sunday week. Write a prediction, how you will check it, a success rule, and your confidence. The original values lock when saved. The app asks you to confirm that you wrote the prediction in your own words without AI help, but cannot independently verify that claim.

After the week ends, add the observed evidence, choose **Right**, **Missed**, or **Not clear yet**, and record a lesson for next week. Each review is appended to local history. An unclear result or unresolved week is not counted as a miss. The original rule cannot be changed after the weekly prediction is locked.

Weekly summary scores exclude synthetic examples and older non-weekly records. They show resolved count, average confidence, actual right rate, and confidence minus right rate in percentage points. A positive gap means confidence was higher than the right rate. Small samples can vary widely. Older Decision Notebook records and their original Brier/calibration history remain readable, but do not enter weekly scores.

## Development

Run checks with:

```sh
python3 -m unittest discover -s tests -v
```

The optional local development server uses `python3 server.py` and `http://127.0.0.1:8352`. Stop it with Control-C. The installed Mac app is the normal way to use Weekly Predictions.

## Data and privacy

Records remain in a private SQLite database outside the app folder. The app does not send data to a service. Use **Export notebook JSON** to save a copy. The database is not encrypted. Deleting `~/.local/share/decision-notebook/` removes the notebook and its legacy history.

## Limits

Evidence and results are entered by the user. Scores are descriptive and become more useful only with repeated, consistent reviews. This app does not provide investment or betting advice. macOS is the only packaged target; source compatibility on other systems is untested.

## License

MIT. See `LICENSE`.
