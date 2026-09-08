import os
import re
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

import pytest


class EnvVar(StrEnum):
    TASK_ACT = "_TASKFZF_TASK_ACT"
    SHOW_KEYS = "_TASKFZF_SHOW"
    RELOAD = "_TASKFZF_RELOAD"
    REPORT = "_TASKFZF_REPORT"
    LIST_CHANGE = "_TASKFZF_LIST_CHANGE"
    INTERNAL = "_TASKFZF_INTERNAL"


class Action(StrEnum):
    DO = "do"
    DELETE = "delete"
    EDIT = "edit"
    ADD = "add"
    ADD_WITH_CONTEXT = "add-with-context"
    APPEND = "append"
    ANNOTATE = "annotate"
    MODIFY = "modify"
    START = "start"
    STOP = "stop"
    UNDO = "undo"
    INFORMATION = "information"


class Binding(StrEnum):
    D = "D"
    X = "X"
    U = "U"
    E = "E"
    T = "T"
    I = "I"
    A = "A"
    N = "N"
    M = "M"
    R = "R"
    C = "C"
    CTRL_R = "ctrl-r"
    S = "S"
    P = "P"
    QUESTION = "?"
    ENTER = "enter"


HAS_TASK = shutil.which("task") is not None
REQUIRES_TASK = pytest.mark.skipif(not HAS_TASK, reason="task binary not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def taskfzf_path() -> Path:
    return Path(__file__).parent / "taskfzf"


@pytest.fixture
def scratch_env(tmp_path: Path) -> dict[str, str]:
    """Scratch env: TASKDATA+TASKRC+XDG_RUNTIME_DIR under tmp_path."""
    xdg = tmp_path / "xdgrun"
    xdg.mkdir()
    taskrc = tmp_path / "taskrc"
    taskrc.write_text(
        f"data.location={tmp_path}\n"
        "confirmation=off\n"
        "verbose=nothing\n"
    )
    env = os.environ.copy()
    env["TASKDATA"] = str(tmp_path)
    env["TASKRC"] = str(taskrc)
    env["XDG_RUNTIME_DIR"] = str(xdg)
    return env


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_taskfzf(
    base_env: dict[str, str],
    *,
    env_overrides: dict[str, str] | None = None,
    args: list[str] | None = None,
    stdin: str = "",
) -> subprocess.CompletedProcess:
    env = dict(base_env)
    if env_overrides:
        env.update(env_overrides)
    bin_path = Path(__file__).parent / "taskfzf"
    return subprocess.run(
        [str(bin_path), *(args or [])],
        input=stdin.encode() if stdin else b"",
        capture_output=True,
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Helpers (require task binary)
# ---------------------------------------------------------------------------

def _create_task(env: dict[str, str], description: str) -> str:
    proc = subprocess.run(
        ["task", "rc.verbose=new-id", "add", description],
        capture_output=True, env=env, text=True, timeout=10,
    )
    match = re.search(r"Created task (\d+)\.", proc.stdout)
    if not match:
        raise RuntimeError(f"could not parse task id from: {proc.stdout!r}")
    return match.group(1)


def _task_field(env: dict[str, str], task_id: str, field: str) -> str:
    proc = subprocess.run(
        ["task", "_get", f"{task_id}.{field}"],
        capture_output=True, env=env, text=True, timeout=10,
    )
    return proc.stdout.strip()


def _task_listing(env: dict[str, str], task_id: str) -> str:
    proc = subprocess.run(
        ["task", task_id, "list"],
        capture_output=True, env=env, text=True, timeout=10,
    )
    return proc.stdout


def _task_info(env: dict[str, str], task_id: str) -> str:
    proc = subprocess.run(
        ["task", "rc.verbose=nothing", task_id, "info"],
        capture_output=True, env=env, text=True, timeout=10,
    )
    return proc.stdout


def _newest_task_id(env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["task", "rc.verbose=new-id", "list"],
        capture_output=True, env=env, text=True, timeout=10,
    )
    nums = re.findall(r"^\s*(\d+)\s", proc.stdout, re.MULTILINE)
    if not nums:
        raise RuntimeError(f"no tasks in listing: {proc.stdout!r}")
    return nums[-1]


# ---------------------------------------------------------------------------
# A. Install prerequisites
# ---------------------------------------------------------------------------

def test_given_taskfzf_script_when_checked_then_is_executable(taskfzf_path: Path):
    # AC-1: taskfzf exists at repo root and is executable
    assert taskfzf_path.is_file(), f"taskfzf missing at {taskfzf_path}"
    assert os.access(str(taskfzf_path), os.X_OK), "taskfzf is not executable"


# ---------------------------------------------------------------------------
# B. CLI forwarding
# ---------------------------------------------------------------------------

@REQUIRES_TASK
def test_given_no_args_when_invoked_then_default_report_used(scratch_env: dict[str, str]):
    # AC-3: no args forwards to task with no args
    _create_task(scratch_env, "ac3 seed")
    proc_tf = run_taskfzf(scratch_env, env_overrides={EnvVar.RELOAD: "true"})
    proc_task = subprocess.run(
        ["task", "rc.defaultwidth=0", "rc.defaultheight=0", "rc.verbose=nothing"],
        capture_output=True, env=scratch_env, text=True, timeout=10,
    )
    tf_first = next((l.strip() for l in proc_tf.stdout.decode().splitlines() if l.strip()), "")
    task_first = next((l.strip() for l in proc_task.stdout.splitlines() if l.strip()), "")
    if tf_first or task_first:
        # Compare tokens (urgency column width may differ)
        assert tf_first.split() == task_first.split(), (
            f"taskfzf tokens {tf_first.split()!r} != task tokens {task_first.split()!r}"
        )


@REQUIRES_TASK
def test_given_report_arg_when_invoked_then_forwarded_to_task(scratch_env: dict[str, str]):
    # AC-4: <report> argument forwards to task
    _create_task(scratch_env, "ac4 seed")
    proc_tf = run_taskfzf(
        scratch_env, env_overrides={EnvVar.RELOAD: "true"}, args=["next"]
    )
    proc_task = subprocess.run(
        ["task", "rc.defaultwidth=0", "rc.defaultheight=0", "rc.verbose=nothing", "next"],
        capture_output=True, env=scratch_env, text=True, timeout=10,
    )
    tf_empty = not proc_tf.stdout.decode().strip()
    task_empty = not proc_task.stdout.strip()
    assert tf_empty == task_empty, (
        f"shape mismatch taskfzf empty={tf_empty} task empty={task_empty}"
    )


@REQUIRES_TASK
def test_given_rc_args_when_invoked_then_passed_through_to_task(scratch_env: dict[str, str]):
    # AC-5: rc. args before report pass through to task
    _create_task(scratch_env, "ac5 seed")
    proc_tf = run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.RELOAD: "true"},
        args=["rc.verbose=nothing", "list"],
    )
    proc_task = subprocess.run(
        ["task", "rc.defaultwidth=0", "rc.defaultheight=0", "rc.verbose=nothing", "list"],
        capture_output=True, env=scratch_env, text=True, timeout=10,
    )
    tf_first = next((l.strip() for l in proc_tf.stdout.decode().splitlines() if l.strip()), "")
    task_first = next((l.strip() for l in proc_task.stdout.splitlines() if l.strip()), "")
    if tf_first or task_first:
        # Compare by whitespace-normalized tokens (column widths can differ).
        assert tf_first.split() == task_first.split(), (
            f"taskfzf first line tokens {tf_first.split()!r} != task first line tokens {task_first.split()!r}"
        )


# ---------------------------------------------------------------------------
# C. Action handlers
# ---------------------------------------------------------------------------

@REQUIRES_TASK
def test_given_pending_task_when_D_invoked_then_marked_done(scratch_env: dict[str, str]):
    # AC-6: D -> task <id> do
    tid = _create_task(scratch_env, "ac6 mark done")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.DO},
        args=[str(fixture)],
    )
    status = _task_field(scratch_env, tid, "status")
    assert "completed" in status.lower(), f"status={status!r} expected Completed"


@REQUIRES_TASK
def test_given_pending_task_when_X_invoked_then_deleted(scratch_env: dict[str, str]):
    # AC-7: X -> task <id> delete
    tid = _create_task(scratch_env, "ac7 delete")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.DELETE},
        args=[str(fixture)],
    )
    proc_check = subprocess.run(
        ["task", tid, "list"],
        capture_output=True, env=scratch_env, timeout=10,
    )
    assert proc_check.returncode != 0, f"task {tid} still present after delete"


@REQUIRES_TASK
def test_given_pending_task_when_E_invoked_then_edit_dispatched(scratch_env: dict[str, str]):
    # AC-8: E -> task <id> edit (EDITOR=true to no-op the editor)
    tid = _create_task(scratch_env, "ac8 edit")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    edit_env = dict(scratch_env)
    edit_env["EDITOR"] = "true"
    proc = run_taskfzf(
        edit_env,
        env_overrides={EnvVar.TASK_ACT: Action.EDIT},
        args=[str(fixture)],
    )
    assert proc.returncode == 0, f"taskfzf exited {proc.returncode}, stderr={proc.stderr!r}"
    proc_check = subprocess.run(
        ["task", tid, "list"],
        capture_output=True, env=scratch_env, timeout=10,
    )
    assert proc_check.returncode == 0, f"task {tid} missing after edit"


@REQUIRES_TASK
def test_given_no_task_when_T_invoked_then_new_task_added(scratch_env: dict[str, str]):
    # AC-9: T -> task add (prompts for attrs then description)
    proc = run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.ADD},
        args=["/dev/null"],
        stdin="project:test\nmy new ac9 task\n",
    )
    proc_check = subprocess.run(
        ["task", "rc.verbose=nothing", "list"],
        capture_output=True, env=scratch_env, text=True, timeout=10,
    )
    assert "my new ac9 task" in proc_check.stdout, (
        f"new task not found in: {proc_check.stdout!r}"
    )


@REQUIRES_TASK
def test_given_context_set_when_I_invoked_then_task_added_with_context_attrs(scratch_env: dict[str, str]):
    # AC-10: I -> task add with attributes from current context
    # NOTE: taskrc syntax must be context.<name>=<rc-args>. The script does
    # `task _get rc.context.<name>` and feeds the result as positional args to
    # `task add`. The dotted form (context.<name>.<attr>=<val>) yields empty
    # from _get and breaks the apply path.
    taskrc_path = Path(scratch_env["TASKRC"])
    with taskrc_path.open("a") as fh:
        fh.write("context.mycontext=project:work\n")
    xdg = Path(scratch_env["XDG_RUNTIME_DIR"])
    (xdg / "taskfzf-current-filter").write_text("rc.context=mycontext\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.ADD_WITH_CONTEXT},
        args=["/dev/null"],
        stdin="\nctx task ac10\n",
    )
    newest = _newest_task_id(scratch_env)
    project = _task_field(scratch_env, newest, "project")
    assert project == "work", f"project={project!r} expected work on task {newest}"


@REQUIRES_TASK
def test_given_pending_task_when_A_invoked_then_description_appended(scratch_env: dict[str, str]):
    # AC-11: A -> task <id> append <stdin>
    tid = _create_task(scratch_env, "ac11 append")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.APPEND},
        args=[str(fixture)],
        stdin="extra text ac11\n",
    )
    desc = _task_field(scratch_env, tid, "description")
    assert "extra text ac11" in desc, f"description after append: {desc!r}"


@REQUIRES_TASK
def test_given_pending_task_when_N_invoked_then_annotation_added(scratch_env: dict[str, str]):
    # AC-12: N -> task <id> annotate <stdin>
    tid = _create_task(scratch_env, "ac12 annotate")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    marker = "ac12_marker_unique_xyz"
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.ANNOTATE},
        args=[str(fixture)],
        stdin=f"{marker}\n",
    )
    info = _task_info(scratch_env, tid)
    assert marker in info, f"annotation {marker!r} not found in info:\n{info}"


@REQUIRES_TASK
def test_given_pending_task_when_M_invoked_then_attribute_modified(scratch_env: dict[str, str]):
    # AC-13: M -> task <id> modify <stdin>
    tid = _create_task(scratch_env, "ac13 modify")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.MODIFY},
        args=[str(fixture)],
        stdin="priority:H\n",
    )
    priority = _task_field(scratch_env, tid, "priority")
    assert priority == "H", f"priority={priority!r} expected H"


@REQUIRES_TASK
def test_given_pending_task_when_S_invoked_then_started(scratch_env: dict[str, str]):
    # AC-14: S -> task <id> start
    tid = _create_task(scratch_env, "ac14 start")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.START},
        args=[str(fixture)],
    )
    start_val = _task_field(scratch_env, tid, "start")
    assert start_val, f"start timestamp empty after S action: {start_val!r}"


@REQUIRES_TASK
def test_given_started_task_when_P_invoked_then_stopped(scratch_env: dict[str, str]):
    # AC-15: P -> task <id> stop
    tid = _create_task(scratch_env, "ac15 stop")
    subprocess.run(
        ["task", tid, "start"],
        capture_output=True, env=scratch_env, timeout=10,
    )
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.STOP},
        args=[str(fixture)],
    )
    start_val = _task_field(scratch_env, tid, "start")
    assert not start_val, f"start timestamp still {start_val!r} after P action"


@REQUIRES_TASK
def test_given_recent_action_when_U_invoked_then_action_undone(scratch_env: dict[str, str]):
    # AC-16: U -> task undo
    tid = _create_task(scratch_env, "ac16 undo")
    subprocess.run(
        ["task", tid, "done"],
        capture_output=True, env=scratch_env, timeout=10,
    )
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.UNDO},
        args=["/dev/null"],
    )
    status = _task_field(scratch_env, tid, "status")
    assert "pending" in status.lower(), f"status={status!r} expected pending after undo"


# ---------------------------------------------------------------------------
# D. List / view bindings
# ---------------------------------------------------------------------------

def test_given_taskfzf_script_when_inspected_then_R_binding_changes_report(taskfzf_path: Path):
    # AC-17: R binding changes the report
    src = taskfzf_path.read_text()
    assert (
        '--bind="R:execute(env _TASKFZF_LIST_CHANGE=report $0)+reload(env _TASKFZF_RELOAD=true $0)"'
        in src
    ), "R bind string not found in script source"


def test_given_taskfzf_script_when_inspected_then_C_binding_changes_context(taskfzf_path: Path):
    # AC-18: C binding changes the context
    src = taskfzf_path.read_text()
    assert (
        '--bind="C:execute(env _TASKFZF_LIST_CHANGE=context $0)+reload(env _TASKFZF_RELOAD=true $0)"'
        in src
    ), "C bind string not found in script source"


def test_given_taskfzf_script_when_inspected_then_CTRL_R_binding_reloads(taskfzf_path: Path):
    # AC-19: CTRL-R reloads current report without losing the filter
    src = taskfzf_path.read_text()
    assert (
        '--bind="ctrl-r:reload(env _TASKFZF_INTERNAL=reload $0)"' in src
    ), "ctrl-r bind string not found in script source"


def test_given_question_binding_when_invoked_then_prints_keys_table(taskfzf_path: Path, scratch_env: dict[str, str]):
    # AC-20: ? binding prints keys summary (bind string present + table renders)
    src = taskfzf_path.read_text()
    assert (
        '--bind="?:execute(env _TASKFZF_SHOW=keys $0 | less)+print-query"' in src
    ), "? bind string not found in script source"
    proc = run_taskfzf(scratch_env, env_overrides={EnvVar.SHOW_KEYS: "keys"})
    stdout = proc.stdout.decode()
    assert stdout.startswith("KEY\tAction"), (
        f"keys table first line wrong: {stdout.splitlines()[0] if stdout else '<empty>'!r}"
    )
    first_tokens = {line.split("\t", 1)[0] for line in stdout.splitlines()}
    for sym in [
        Binding.D, Binding.X, Binding.U, Binding.E, Binding.T, Binding.I, Binding.A,
        Binding.N, Binding.M, Binding.R, Binding.C, Binding.CTRL_R, Binding.S,
        Binding.P, Binding.QUESTION,
    ]:
        assert sym in first_tokens, (
            f"binding {sym!r} not in keys table (first tokens: {first_tokens!r})"
        )


def test_given_taskfzf_script_when_inspected_then_enter_binding_shows_information(taskfzf_path: Path):
    # AC-21: enter binding dispatches task information
    src = taskfzf_path.read_text()
    assert (
        '--bind="enter:execute(env _TASKFZF_TASK_ACT=information $0 {+f} | less)"' in src
    ), "enter bind string not found in script source"


EXPECTED_ACTION_BINDINGS = [
    '--bind="D:execute(env _TASKFZF_TASK_ACT=do $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="X:execute(env _TASKFZF_TASK_ACT=delete $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="U:execute(env _TASKFZF_TASK_ACT=undo $0< /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="E:execute(env _TASKFZF_TASK_ACT=edit $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="T:execute(env _TASKFZF_TASK_ACT=add $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="I:execute(env _TASKFZF_TASK_ACT=add-with-context $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="A:execute(env _TASKFZF_TASK_ACT=append $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="N:execute(env _TASKFZF_TASK_ACT=annotate $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="M:execute(env _TASKFZF_TASK_ACT=modify $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="S:execute(env _TASKFZF_TASK_ACT=start $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
    '--bind="P:execute(env _TASKFZF_TASK_ACT=stop $0 {+f} < /dev/tty > /dev/tty 2>&1 )+reload(env _TASKFZF_RELOAD=true $0)"',
]


def test_given_taskfzf_script_when_inspected_then_action_bindings_reload(taskfzf_path: Path):
    # AC-28: action bindings use +reload instead of +print-query so fzf
    # stays alive and refreshes the task list after each action.
    src = taskfzf_path.read_text()
    for expected in EXPECTED_ACTION_BINDINGS:
        assert expected in src, f"action binding missing: {expected}"


# ---------------------------------------------------------------------------
# E. Report-format requirement
# ---------------------------------------------------------------------------

def test_given_non_numeric_first_column_when_action_invoked_then_warning(scratch_env: dict[str, str]):
    # AC-22: non-numeric first column in non-all report triggers warning
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text("hello world\n")
    proc = run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.DO},
        args=[str(fixture)],
        stdin="\n",
    )
    stderr = proc.stderr.decode()
    assert proc.returncode != 0, f"expected non-zero exit, got {proc.returncode}"
    assert "first column" in stderr or "ID/UUID" in stderr, (
        f"expected warning in stderr, got: {stderr!r}"
    )


# ---------------------------------------------------------------------------
# F. Static / environmental behaviors
# ---------------------------------------------------------------------------

def test_given_all_report_when_action_invoked_then_uuids_extracted(scratch_env: dict[str, str]):
    # AC-24: 'all' report extracts 8-hex UUIDs from selected lines (no warning)
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text("abc12345 some description\n")
    proc = run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.REPORT: "all", EnvVar.TASK_ACT: Action.DO},
        args=[str(fixture)],
    )
    stderr = proc.stderr.decode()
    assert "first column" not in stderr, f"unexpected first-column warning: {stderr!r}"
    assert "ID/UUID" not in stderr, f"unexpected ID/UUID warning: {stderr!r}"


def test_given_multiple_tasks_selected_when_modify_invoked_then_first_only(scratch_env: dict[str, str]):
    # AC-25: modify/append/annotate with multiple selected tasks warns, uses only first
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text("1\n2\n")
    proc = run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.APPEND},
        args=[str(fixture)],
        stdin="\nextra\n",
    )
    stderr = proc.stderr.decode()
    assert "Only the first task" in stderr, (
        f"stderr missing Only-the-first-task warning: {stderr!r}"
    )
