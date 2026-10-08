# Local benchmark queue GUI

A small, standard-library Tkinter front end for sequential Ollama role campaigns.
Each queue item invokes the existing `tools/campaigns/run-all-roles.ps1` once.
That CLI still owns the Planner, Governor, Worker, Tester, Reviewer, evidence,
and review-workbook behavior.

## Launch on Windows

Use the existing checkout and Python 3.10+ with Tcl/Tk. The standard Windows
Python installer includes Tcl/Tk; the GUI needs no pip dependencies. Ollama and
the existing benchmark prerequisites must already work for the CLI.

From PowerShell:

```powershell
Set-Location C:\Projects\local-model-bench-flashnext
.\tools\gui\benchmark-queue.cmd
```

You can also double-click `tools\gui\benchmark-queue.cmd`. It prefers the
checkout's `.venv\Scripts\python.exe`, then `py.exe -3`, then `python.exe`.
If launch fails, the command window keeps the error visible.

To choose Python directly:

```powershell
py -3 .\tools\gui\benchmark-queue.py
```

The Python launcher adds this checkout's `src` directory to its own import
path. An editable install is unnecessary. An installed package also supports
`python -m localbench.queue_gui`.

## Run a queue

1. Click **Refresh Ollama Models**. A refresh also happens on normal startup.
   Discovery runs `ollama list` in the background, with a 15-second timeout.
   V1 lists the local endpoint `http://127.0.0.1:11434`, matching the CLI's
   default even if your shell's `OLLAMA_HOST` points elsewhere.
2. Click model rows to toggle selection; Ctrl is unnecessary. **Select all**
   and **Clear selection** are available.
3. Click **Add selected to queue**. The list order becomes queue order.
   Select a Waiting queue row and use **Move up** / **Move down** to reorder it.
   **Remove waiting** removes that row. Duplicate tags in one queue are ignored.
4. Choose `screen` or `qualification`, check the governor root, and leave
   advanced fields blank unless you want to override the CLI.
5. Click **Start Queue**. If the queue is empty, Start first adds the selected
   model rows. One process runs at a time, from the checkout's root directory.
   The next model starts only after the previous process has exited and its
   result has been handled and saved.

The current model, queue state, completed count, waiting count, elapsed time per
item, exit code, and captured `RUN_DIR` are visible. The terminal receives merged
stdout/stderr as the child writes it, including partial lines. It retains the
most recent 300,000 characters and follows new output when already scrolled to
the bottom. Scroll up to inspect earlier output without being pulled back down.

Settings are saved with the queue and fixed once its first item starts, including
while Paused or Stopped. Use **New Queue** to change settings for another batch
or deliberately rerun a completed, failed, or interrupted model. New Queue clears
only the queue list; the CLI's benchmark evidence stays in place.

### Settings and defaults

| Setting | Initial value / authoritative CLI default | Forwarded argument |
|---|---|---|
| Runtime | `ollama`, fixed in V1 | `-Runtime ollama` |
| Phase | `screen`; also accepts `qualification` | `-Phase` |
| Governor root | `C:\Projects\governor` | `-GovernorRoot` |
| Context tokens | Blank uses `32768` | `-ContextTokens` |
| Max output tokens | Blank uses `8192` | `-MaxOutputTokens` |
| Timeout seconds | Blank uses `600` | `-TimeoutSeconds` |
| Keep-alive seconds | Blank uses `3600` | `-KeepAliveSeconds` |

These are the current defaults in `run-all-roles.ps1`. Blank advanced fields
**omit the argument**, so the runner remains authoritative if its defaults change.
Context and output overrides must be positive 32-bit integers. Timeout must be a
finite positive number. Keep-alive accepts finite values, including `0` and `-1`,
and forwards them unchanged. The queue does not impose an additional total-model
timeout or change model residency.

For example, a default queue item builds this command as an argument list with
`shell=False`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\campaigns\run-all-roles.ps1 `
  -Runtime ollama -Model gemma3:27b -Phase screen `
  -GovernorRoot C:\Projects\governor
```

### Pause, continue, and stop

| Control | Behavior |
|---|---|
| **Pause After Current** | Lets the active model's entire CLI invocation finish. If work remains, the queue becomes Paused before another model starts. It never suspends inference. |
| **Continue** | Starts the next Waiting model from a Paused or Stopped queue. It does not rerun finished rows. |
| **Stop After Current** | Finishes the active model and sets the queue to Stopped, leaving remaining rows Waiting. Stop takes precedence over a pending pause. |
| **Emergency Stop…** | After its explicit partial-evidence warning, requests termination of the current process tree owned by this GUI. The queue waits for actual process exit. It does not stop the shared Ollama service or terminate recovered PIDs. |

If no Waiting items remain, the queue becomes Complete even when pause/stop was
requested during the last item. Clicking pause/stop between models takes effect
before the pending next launch.

Closing the window during a run offers to **finish the current model and then
close**. The window stays open until that process exits. Canceling the close
keeps the queue running normally. Waiting rows remain available after reopening.

### Completion and evidence

**Complete means the CLI exited with code 0; it is not a model-quality verdict.**
Review the runner's standardized outputs to judge the candidate:

- `review/review-package.xlsx`
- `review/review-package.json`
- `review/case-results.csv`
- `review/role-summary.csv`

A nonzero exit marks that item Failed and normally proceeds to the next Waiting
model. A process-launch failure stops the queue so a missing PowerShell executable
does not fail every remaining item. Output-reader failures also mark a run Failed.
Captured evidence paths remain attached to failures when the CLI emitted
`RUN_DIR=`. The GUI does not infer a run directory when that marker is absent.

Select a row with a captured directory and click **Open run folder** or
**Open review workbook**. The CLI's output location is unchanged.

## Persistence and recovery

State is saved atomically in:

```text
<checkout>\local-state\queue-gui\queue.json
```

It contains queue order, settings, item states, timestamps, PIDs, exit codes,
errors, and captured run directories. It does not save credentials, an environment
dump, or the terminal transcript. `local-state/` is already ignored by Git.
An OS-held instance lock allows only one GUI per checkout, even with a custom
state-file path. This does not lock out a separately launched CLI or another
checkout using the same Ollama server.

Reopening never starts a benchmark automatically. Waiting and finished entries
are retained. A run that was active when the GUI crashed becomes **Interrupted**,
and its queue becomes Paused. It is not automatically rerun or reattached.
Before continuing or clearing that recovered queue, the GUI checks saved PIDs
read-only and blocks while a previous process may still be active. If no PID was
saved before the crash, it asks you to verify that the previous runner has stopped.
The GUI never kills a process based on a saved PID.

An unreadable state file is preserved and reported. **New Queue** first renames
it to an `*.invalid-<timestamp>.json` backup before starting fresh. If saving fails,
further launches pause and an error remains visible; an active benchmark can
finish. Fix the storage problem, then Continue to retry saving and resume.

To use another JSON path while retaining the checkout's instance lock:

```powershell
py -3 .\tools\gui\benchmark-queue.py --state-file C:\BenchQueue\queue.json
```

## Development and deterministic validation

The implementation is separate from the benchmark engine:

- `src/localbench/queue_gui/core.py`: settings, argv, parsing, queue transitions,
  and JSON persistence.
- `src/localbench/queue_gui/process.py`: owned subprocess, streamed events, model
  discovery, and the instance lock.
- `src/localbench/queue_gui/app.py`: Tk widgets and all queue scheduling on the UI
  thread.
- `tools/gui/benchmark-queue.py` and `.cmd`: checkout launchers.

Run the focused tests from the repository root:

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'src')
py -3 -m unittest discover -s tests -p 'test_queue_gui*.py' -v
```

The tests use deterministic state transitions, fake runners/discovery, and
harmless subprocess fixtures. They never call Ollama or run a real benchmark.
Widget tests create actual Tk widgets; they skip on hosts without a display.
The dedicated Windows CI job sets `LOCALBENCH_REQUIRE_TK=1`, requiring actual
Tk startup rather than accepting that skip, and checks the checkout launchers.

No role packets, accepted benchmark batteries, evaluation rules, or workbook
generation are implemented here. The existing CLI remains independently usable.
