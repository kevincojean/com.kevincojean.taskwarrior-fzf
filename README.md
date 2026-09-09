# Taskwarrior fzf interface

An [fzf](https://github.com/junegunn/fzf) based UI for
[taskwarrior](https://taskwarrior.org/), implemented as a `/bin/sh`
script.

## Install

1. Link / Copy / Move the file `taskfzf` from this repo to your `$PATH`.
2. Make sure you have [fzf 0.19.0 or
   newer](https://github.com/junegunn/fzf/releases) installed.

## Usage

### Command Line Arguments

Launching `taskfzf`, will present you an `fzf` interface where every
task is a line you can filter out using `fzf`'s magical search.

Without arguments, you'll see the list of tasks `task` would list if
given no arguments.

You can supply a `report` argument (e.g `ls`, `list`, `next`..) to
`taskfzf` as you'd supply `task`.

Besides that, `taskfzf` also accepts modifications to your config using
`rc.` arguments given right before the optional report argument.

### Key Bindings

`taskfzf` uses [`fzf`'s
bindings](https://www.mankier.com/1/fzf#Key_Bindings) to perform actions
over the highlighted task or to change the list of tasks presented.
Pressing `?` prints a summary of all key bindings and their actions but
the lists here explain a bit more.

#### Perform an action over the selected tasks

- `D` marks the tasks as done (`task do`).
- `X` deletes the tasks (`task del`).
- `E` edits the task in your editor (`task edit`).
- `O` opens the selected task in [taskopen](https://github.com/ValiValpas/taskopen).
- `I` adds a new task, with context of the currently highlighted task.
- `A` appends a text to the tasks using a shell input (`task append`).
- `M` modifies a task using a shell input (`task modify`).

> **IMPORTANT:** The script expects all reports to put in their 1st
> column the task's number. You will get a warning when trying to perform
> actions upon a certain task if that's not the case. Adjust your reports
> accordingly!

#### Other actions

- `U` undo the last action performed (`task undo`).
- `S` toggles the task between started and stopped: `start` if pending,
  `stop` if already started.
- `enter` show the highlighted task's information (`task info`).

#### Change / Reload the current list of tasks

Each of the following key bindings changes the list of tasks you can
perform an actions upon. `taskfzf` does so by reprinting the list of
tasks with a different context (`rc.context`) or with a different
"report".

*Choosing* a different context/report is also performed by `fzf`.
`task reports` or `task contexts` supply the list of candidates.

In the tasks view, you can prompt for a different report / context
using:

- `R` changes the current "report" (`task reports`).
- `C` changes the current context (`task contexts`).
- `ctrl-r` reloads the current report, useful when another instance
  of `task` changes your tasks.

## Running the Tests

### Prerequisites

- [Python](https://www.python.org/) 3.10 or newer
- [pytest](https://pytest.org) 7 or newer
- `task` and `fzf` installed and on `$PATH`

### Install pytest

```sh
pip install pytest
```

### Run the tests

From the repository root:

```sh
python3 -m pytest taskfzf-test.py -v
```
