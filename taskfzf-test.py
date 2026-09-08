import fcntl
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import termios
import time
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
    ADD_POPUP = "add-popup"
    APPEND = "append"
    MODIFY = "modify"
    START = "start"
    STOP = "stop"
    UNDO = "undo"
    TOGGLE = "toggle"
    TASKOPEN = "taskopen"
    INFORMATION = "information"


class Binding(StrEnum):
    D = "D"
    X = "X"
    U_LOWER = "u"
    U_UPPER = "U"
    E_UPPER = "E"
    A_LOWER = "a"
    A_UPPER = "A"
    E_LOWER = "e"
    M = "M"
    S_LOWER = "s"
    S_UPPER = "S"
    R = "R"
    C = "C"
    CTRL_R = "ctrl-r"
    CTRL_SLASH = "ctrl-/"
    QUESTION = "?"


CURRENT_BINDINGS = frozenset({
    (Binding.D, Action.DO),
    (Binding.X, Action.DELETE),
    (Binding.U_LOWER, Action.UNDO),
    (Binding.U_UPPER, Action.UNDO),
    (Binding.E_UPPER, Action.TASKOPEN),
    (Binding.A_LOWER, Action.ADD_POPUP),
    (Binding.A_UPPER, Action.ADD_WITH_CONTEXT),
    (Binding.E_LOWER, Action.TASKOPEN),
    (Binding.M, Action.MODIFY),
    (Binding.S_LOWER, Action.TOGGLE),
    (Binding.S_UPPER, Action.TOGGLE),
    (Binding.R, "report"),
    (Binding.C, "context"),
    (Binding.CTRL_R, "reload"),
    (Binding.QUESTION, "keys"),
    (Binding.CTRL_SLASH, Action.INFORMATION),
})

REMOVED_BINDINGS = frozenset({"P", "T", "N", "ctrl-c", "I", "enter", "shift-c"})


HAS_TASK = shutil.which("task") is not None
HAS_TASKOPEN = shutil.which("taskopen") is not None
HAS_FZF = shutil.which("fzf") is not None
REQUIRES_TASK = pytest.mark.skipif(not HAS_TASK, reason="task binary not installed")
REQUIRES_TASKOPEN = pytest.mark.skipif(
    not HAS_TASKOPEN, reason="taskopen binary not installed"
)
REQUIRES_FZF = pytest.mark.skipif(not HAS_FZF, reason="fzf binary not installed")


@pytest.fixture
def taskfzf_path() -> Path:
    return Path(__file__).parent / "taskfzf"


@pytest.fixture
def scratch_env(tmp_path: Path) -> dict[str, str]:
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
    env.setdefault("TERM", "xterm")
    bin_path = Path(__file__).parent / "taskfzf"
    return subprocess.run(
        [str(bin_path), *(args or [])],
        input=stdin.encode() if stdin else b"",
        capture_output=True,
        env=env,
        timeout=30,
    )


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


def _newest_task_id(env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["task", "rc.verbose=new-id", "list"],
        capture_output=True, env=env, text=True, timeout=10,
    )
    nums = re.findall(r"^\s*(\d+)\s", proc.stdout, re.MULTILINE)
    if not nums:
        raise RuntimeError(f"no tasks in listing: {proc.stdout!r}")
    return nums[-1]


def _keys_table(env: dict[str, str]) -> list[tuple[str, str]]:
    proc = run_taskfzf(env, env_overrides={EnvVar.SHOW_KEYS: "keys"})
    assert proc.returncode == 0, f"taskfzf keys exit={proc.returncode}: {proc.stderr!r}"
    rows = []
    for line in proc.stdout.decode().splitlines()[2:]:
        if not line.strip():
            continue
        key, _, help_text = line.partition("\t")
        rows.append((key, help_text))
    return rows


def _bindings_data_section(taskfzf_path: Path) -> str:
    src = taskfzf_path.read_text()
    match = re.search(r"BINDINGS_DATA='\n(.*?)\n'", src, re.DOTALL)
    if not match:
        raise AssertionError("BINDINGS_DATA not found in script source")
    return match.group(1)


def test_given_taskfzf_script_when_checked_then_is_executable(taskfzf_path: Path):
    # AC-1
    assert taskfzf_path.is_file(), f"taskfzf missing at {taskfzf_path}"
    assert os.access(str(taskfzf_path), os.X_OK), "taskfzf is not executable"


@REQUIRES_TASK
def test_given_no_args_when_invoked_then_default_report_used(scratch_env: dict[str, str]):
    # AC-3
    _create_task(scratch_env, "ac3 seed")
    proc_tf = run_taskfzf(scratch_env, env_overrides={EnvVar.RELOAD: "true"})
    proc_task = subprocess.run(
        ["task", "rc.defaultwidth=0", "rc.defaultheight=0", "rc.verbose=nothing"],
        capture_output=True, env=scratch_env, text=True, timeout=10,
    )
    tf_first = next((l.strip() for l in proc_tf.stdout.decode().splitlines() if l.strip()), "")
    task_first = next((l.strip() for l in proc_task.stdout.splitlines() if l.strip()), "")
    if tf_first or task_first:
        assert tf_first.split() == task_first.split(), (
            f"taskfzf tokens {tf_first.split()!r} != task tokens {task_first.split()!r}"
        )


@REQUIRES_TASK
def test_given_report_arg_when_invoked_then_forwarded_to_task(scratch_env: dict[str, str]):
    # AC-4
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
    # AC-5
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
        assert tf_first.split() == task_first.split(), (
            f"taskfzf first line tokens {tf_first.split()!r} != task first line tokens {task_first.split()!r}"
        )


@REQUIRES_TASK
def test_given_pending_task_when_D_invoked_then_marked_done(scratch_env: dict[str, str]):
    # AC-6
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
    # AC-7
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
def test_given_pending_task_when_E_upper_invoked_then_edit_dispatched(scratch_env: dict[str, str]):
    # AC-8
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
def test_given_no_task_when_add_action_invoked_then_new_task_added(scratch_env: dict[str, str]):
    # AC-9: legacy add action still works via env var. T-004 / T-008 changed
    # the user-facing binding, not the internal action verb.
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
    # AC-10
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
    # AC-11
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
def test_given_pending_task_when_M_invoked_then_attribute_modified(scratch_env: dict[str, str]):
    # AC-13: N annotate removed by T-005, AC-12 is gone.
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
def test_given_pending_task_when_s_toggle_invoked_then_started(scratch_env: dict[str, str]):
    # T-006: s toggle starts a pending task.
    tid = _create_task(scratch_env, "ac14 toggle start")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.TOGGLE},
        args=[str(fixture)],
    )
    start_val = _task_field(scratch_env, tid, "start")
    assert start_val, f"start timestamp empty after toggle: {start_val!r}"


@REQUIRES_TASK
def test_given_started_task_when_s_toggle_invoked_then_stopped(scratch_env: dict[str, str]):
    # T-006: s toggle on a started task stops it.
    tid = _create_task(scratch_env, "ac15 toggle stop")
    subprocess.run(
        ["task", tid, "start"],
        capture_output=True, env=scratch_env, timeout=10,
    )
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.TOGGLE},
        args=[str(fixture)],
    )
    start_val = _task_field(scratch_env, tid, "start")
    assert not start_val, f"start timestamp still {start_val!r} after toggle stop"


@REQUIRES_TASK
def test_given_recent_action_when_u_invoked_then_action_undone(scratch_env: dict[str, str]):
    # T-003: u replaces U for undo.
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


@REQUIRES_TASK
@REQUIRES_TASKOPEN
def test_given_pending_task_when_e_invoked_then_taskopen_dispatched(scratch_env: dict[str, str]):
    # T-002: e -> taskopen <id>. taskopen prints either "Attaching to task N"
    # or "No actions applicable." depending on the task's metadata; either is
    # proof of dispatch against the right task id.
    tid = _create_task(scratch_env, "ac17 taskopen")
    fixture = Path(scratch_env["TASKDATA"]) / "fixture.txt"
    fixture.write_text(f"{tid}\n")
    proc = run_taskfzf(
        scratch_env,
        env_overrides={EnvVar.TASK_ACT: Action.TASKOPEN},
        args=[str(fixture)],
    )
    out = (proc.stdout + proc.stderr).decode()
    assert (
        f"task {tid}" in out
        or f"Attaching to task {tid}" in out
        or "No actions applicable" in out
    ), f"taskopen did not run for task {tid}: stdout+stderr={out!r}"


def test_given_taskfzf_script_when_inspected_then_has_bindings_data(taskfzf_path: Path):
    # T-009
    src = taskfzf_path.read_text()
    assert "BINDINGS_DATA=" in src, "BINDINGS_DATA declaration not found in script"
    body = _bindings_data_section(taskfzf_path)
    assert body.strip(), "BINDINGS_DATA body is empty"


def test_given_bindings_data_when_parsed_then_keys_match_keys_table(taskfzf_path: Path, scratch_env: dict[str, str]):
    # T-009
    body = _bindings_data_section(taskfzf_path)
    data_keys = set()
    for line in body.splitlines():
        if not line.strip():
            continue
        kind, key, _, _ = line.split("|", 3)
        assert kind in {"task-act", "undo", "list-change", "reload", "show-keys", "show-info"}, (
            f"unknown kind {kind!r} in BINDINGS_DATA line {line!r}"
        )
        data_keys.add(key)

    table_keys = {key for key, _ in _keys_table(scratch_env)}
    missing = data_keys - table_keys
    assert not missing, f"BINDINGS_DATA keys not rendered in help table: {missing}"


@REQUIRES_TASK
def test_given_keys_table_when_rendered_then_current_bindings_present(scratch_env: dict[str, str]):
    # T-009
    rows = _keys_table(scratch_env)
    keys_present = {k for k, _ in rows}
    for expected_key, _ in CURRENT_BINDINGS:
        assert expected_key in keys_present, (
            f"current binding {expected_key!r} missing from keys table: {keys_present!r}"
        )


def test_given_keys_table_when_rendered_then_removed_bindings_absent(scratch_env: dict[str, str]):
    # T-005 / T-007 / T-008 / T-003
    rows = _keys_table(scratch_env)
    keys_present = {k for k, _ in rows}
    for removed in REMOVED_BINDINGS:
        assert removed not in keys_present, (
            f"removed binding {removed!r} still present in keys table: {keys_present!r}"
        )


def test_given_bindings_data_when_parsed_then_includes_new_keys(taskfzf_path: Path):
    # T-001 / T-002 / T-003 / T-004 / T-006
    body = _bindings_data_section(taskfzf_path)
    data_keys = set()
    for line in body.splitlines():
        if not line.strip():
            continue
        _, key, _, _ = line.split("|", 3)
        data_keys.add(key)
    for new_key in ("U", "S", "ctrl-/"):
        assert new_key in data_keys, f"new binding {new_key!r} missing from BINDINGS_DATA"


def test_given_taskfzf_script_when_inspected_then_uses_gen_all_binds(taskfzf_path: Path):
    # T-009
    src = taskfzf_path.read_text()
    assert "$(gen_all_binds)" in src, "fzf invocation must consume gen_all_binds() output"


def test_given_taskfzf_script_when_inspected_then_keys_table_is_function(taskfzf_path: Path):
    # T-009
    src = taskfzf_path.read_text()
    assert "print_keys_table()" in src, "print_keys_table() not invoked"
    assert "print_keys_table() {" in src, "print_keys_table() function not defined"


def test_given_non_numeric_first_column_when_action_invoked_then_warning(scratch_env: dict[str, str]):
    # AC-22
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


def test_given_all_report_when_action_invoked_then_uuids_extracted(scratch_env: dict[str, str]):
    # AC-24
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
    # AC-25: annotate removed by T-005 so the warning case covers modify/append.
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


def _write_fake_fzf(bin_dir: Path) -> Path:
    script = bin_dir / "fzf"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        "  echo '0.65.2'\n"
        "  exit 0\n"
        "fi\n"
        "i=0\n"
        "for a in \"$@\"; do\n"
        "  i=$((i+1))\n"
        "  printf 'ARG %d<<%s>>\\n' \"$i\" \"$a\"\n"
        "done\n"
        "exit 0\n"
    )
    script.chmod(0o755)
    return script


def test_given_fzf_invoked_then_bindings_passed_as_single_argv_elements(
    scratch_env: dict[str, str],
):
    bin_dir = Path(scratch_env["TASKDATA"]) / "bin"
    bin_dir.mkdir()
    _write_fake_fzf(bin_dir)
    env = dict(scratch_env)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    proc = subprocess.run(
        [str(Path(__file__).parent / "taskfzf")],
        input=b"",
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"taskfzf exited {proc.returncode}, stderr={proc.stderr.decode()!r}"
    )
    binding_args = [
        line[line.index("<<") + 2 : line.rindex(">>")]
        for line in proc.stdout.decode().splitlines()
        if line.startswith("ARG ") and "--bind=" in line
    ]
    assert len(binding_args) == len(CURRENT_BINDINGS), (
        f"expected {len(CURRENT_BINDINGS)} --bind args to fzf, "
        f"got {len(binding_args)}: {binding_args!r}"
    )
    for binding in binding_args:
        assert binding.startswith("--bind="), binding
        assert ":execute(" in binding or ":reload(" in binding, (
            f"binding missing execute/reload action (word-split?): {binding!r}"
        )
    do_bind = next((b for b in binding_args if b.startswith("--bind=D:")), "")
    assert do_bind, f"D binding not found in: {binding_args!r}"
    assert "_TASKFZF_TASK_ACT=do" in do_bind, (
        f"D binding fragmented; expected _TASKFZF_TASK_ACT=do in one arg, "
        f"got: {do_bind!r}"
    )
    assert "+reload(" in do_bind, (
        f"D binding missing +reload suffix: {do_bind!r}"
    )


def test_given_fzf_invoked_then_no_unknown_action_error(scratch_env: dict[str, str]):
    proc = subprocess.run(
        [str(Path(__file__).parent / "taskfzf")],
        input=b"",
        capture_output=True,
        env={**scratch_env, "TERM": "xterm"},
        timeout=10,
    )
    combined = (proc.stdout + proc.stderr).decode()
    assert "unknown action" not in combined, (
        f"fzf rejected a binding; raw output:\n{combined}"
    )
    assert "unsupported key" not in combined, (
        f"fzf rejected a binding key; raw output:\n{combined}"
    )


def _write_fzf_capture_stdin(bin_dir: Path, capture_path: Path, return_name: str) -> Path:
    script = bin_dir / "fzf"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        "  echo '0.65.2'\n"
        "  exit 0\n"
        "fi\n"
        f"cat > '{capture_path}'\n"
        f"printf '%s\\n' '{return_name}'\n"
    )
    script.chmod(0o755)
    return script


@REQUIRES_TASK
def test_given_context_change_when_invoked_then_fzf_receives_only_context_names(
    scratch_env: dict[str, str],
):
    taskrc_path = Path(scratch_env["TASKRC"])
    with taskrc_path.open("a") as fh:
        fh.write("context.alpha=+alpha\n")
        fh.write("context.bravo=+bravo\n")
        fh.write("context.charlie=+charlie\n")

    bin_dir = Path(scratch_env["TASKDATA"]) / "bin"
    bin_dir.mkdir()
    capture_path = bin_dir / "captured_stdin.txt"
    _write_fzf_capture_stdin(bin_dir, capture_path, "bravo")

    env = dict(scratch_env)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    proc = subprocess.run(
        [str(Path(__file__).parent / "taskfzf")],
        input=b"",
        capture_output=True,
        env={EnvVar.LIST_CHANGE: "context", **env},
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"taskfzf exited {proc.returncode}, stderr={proc.stderr.decode()!r}"
    )
    assert capture_path.exists(), "fzf was never invoked (no stdin captured)"
    lines = [l for l in capture_path.read_text().splitlines() if l.strip()]

    assert set(lines) == {"alpha", "bravo", "charlie"}, (
        f"fzf input should be exactly the context names; got {set(lines)!r} "
        f"from lines={lines!r}"
    )


@REQUIRES_TASK
def test_given_context_change_when_invoked_then_filter_file_updated(
    scratch_env: dict[str, str],
):
    taskrc_path = Path(scratch_env["TASKRC"])
    with taskrc_path.open("a") as fh:
        fh.write("context.alpha=+alpha\n")
        fh.write("context.bravo=+bravo\n")

    bin_dir = Path(scratch_env["TASKDATA"]) / "bin"
    bin_dir.mkdir()
    capture_path = bin_dir / "captured_stdin.txt"
    _write_fzf_capture_stdin(bin_dir, capture_path, "bravo")

    env = dict(scratch_env)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    proc = subprocess.run(
        [str(Path(__file__).parent / "taskfzf")],
        input=b"",
        capture_output=True,
        env={EnvVar.LIST_CHANGE: "context", **env},
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"taskfzf exited {proc.returncode}, stderr={proc.stderr.decode()!r}"
    )
    marker = Path(env["XDG_RUNTIME_DIR"]) / "taskfzf-current-filter"
    content = marker.read_text().strip()
    assert "rc.context=bravo" in content, (
        f"marker file missing rc.context=bravo; got {content!r}"
    )


@REQUIRES_TASK
def test_given_context_change_twice_when_invoked_then_marker_reflects_second(
    scratch_env: dict[str, str],
):
    taskrc_path = Path(scratch_env["TASKRC"])
    with taskrc_path.open("a") as fh:
        fh.write("context.alpha=+alpha\n")
        fh.write("context.bravo=+bravo\n")
        fh.write("context.charlie=+charlie\n")

    bin_dir = Path(scratch_env["TASKDATA"]) / "bin"
    bin_dir.mkdir()
    capture1 = bin_dir / "captured1.txt"
    _write_fzf_capture_stdin(bin_dir, capture1, "bravo")

    env = dict(scratch_env)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    marker = Path(env["XDG_RUNTIME_DIR"]) / "taskfzf-current-filter"

    proc1 = subprocess.run(
        [str(Path(__file__).parent / "taskfzf")],
        input=b"",
        capture_output=True,
        env={EnvVar.LIST_CHANGE: "context", **env},
        timeout=10,
    )
    assert proc1.returncode == 0, (
        f"first taskfzf exited {proc1.returncode}, stderr={proc1.stderr.decode()!r}"
    )
    assert "rc.context=bravo" in marker.read_text(), (
        f"first change missing rc.context=bravo; got {marker.read_text()!r}"
    )

    capture2 = bin_dir / "captured2.txt"
    _write_fzf_capture_stdin(bin_dir, capture2, "charlie")

    proc2 = subprocess.run(
        [str(Path(__file__).parent / "taskfzf")],
        input=b"",
        capture_output=True,
        env={EnvVar.LIST_CHANGE: "context", **env},
        timeout=10,
    )
    assert proc2.returncode == 0, (
        f"second taskfzf exited {proc2.returncode}, stderr={proc2.stderr.decode()!r}"
    )
    assert "rc.context=charlie" in marker.read_text(), (
        f"second change did not update marker; got {marker.read_text()!r}"
    )
    assert "rc.context=bravo" not in marker.read_text(), (
        f"marker still has the first context after the second change; "
        f"got {marker.read_text()!r}"
    )


def _run_taskfzf_in_pty(
    base_env: dict[str, str],
    *,
    env_overrides: dict[str, str],
    keys: list[str],
    settle: float = 1.0,
    timeout: float = 20.0,
) -> str:
    """Run taskfzf on a real pty so the real fzf TUI runs and reacts to keys.

    The fake-fzf helpers above cannot cover the picker: they ignore --bind
    completely, so they say nothing about whether fzf's selection actually
    reaches the surrounding command substitution.
    """
    env = dict(base_env)
    env.update(env_overrides)
    env["TERM"] = "xterm"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    proc = subprocess.Popen(
        [str(Path(__file__).parent / "taskfzf")],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    output = b""
    try:
        # fzf's accept takes whatever is highlighted at that instant, so the
        # query must be given time to filter before Enter is sent.
        for chunk_keys in keys:
            time.sleep(settle)
            os.write(master, chunk_keys.encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
            elif proc.poll() is not None:
                break
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        os.close(master)
    return output.decode(errors="replace")


@REQUIRES_TASK
@REQUIRES_FZF
def test_given_context_picked_in_real_fzf_then_marker_records_that_context(
    scratch_env: dict[str, str],
):
    taskrc_path = Path(scratch_env["TASKRC"])
    with taskrc_path.open("a") as fh:
        fh.write("context.alpha=+alpha\n")
        fh.write("context.bravo=+bravo\n")
        fh.write("context.charlie=+charlie\n")

    screen = _run_taskfzf_in_pty(
        scratch_env,
        env_overrides={EnvVar.LIST_CHANGE: "context"},
        keys=["bravo", "\r"],
    )
    marker = Path(scratch_env["XDG_RUNTIME_DIR"]) / "taskfzf-current-filter"
    assert marker.read_text().strip() == "rc.context=bravo", (
        f"picking 'bravo' in the real fzf must write rc.context=bravo; "
        f"marker={marker.read_text()!r} screen tail={screen[-300:]!r}"
    )


@REQUIRES_TASK
@REQUIRES_FZF
def test_given_report_picked_in_real_fzf_then_marker_records_report_name_only(
    scratch_env: dict[str, str],
):
    # The reports listing is two columns (name + description), so only the
    # first field may reach the marker file.
    screen = _run_taskfzf_in_pty(
        scratch_env,
        env_overrides={EnvVar.LIST_CHANGE: "report"},
        keys=["overdue", "\r"],
    )
    marker = Path(scratch_env["XDG_RUNTIME_DIR"]) / "taskfzf-current-filter"
    assert marker.read_text().strip() == "overdue", (
        f"picking the overdue report must write just the report name; "
        f"marker={marker.read_text()!r} screen tail={screen[-300:]!r}"
    )


@REQUIRES_TASK
@REQUIRES_FZF
def test_given_context_picker_cancelled_in_real_fzf_then_filter_unchanged(
    scratch_env: dict[str, str],
):
    taskrc_path = Path(scratch_env["TASKRC"])
    with taskrc_path.open("a") as fh:
        fh.write("context.alpha=+alpha\n")
        fh.write("context.bravo=+bravo\n")

    marker = Path(scratch_env["XDG_RUNTIME_DIR"]) / "taskfzf-current-filter"
    marker.write_text("rc.context=alpha\n")

    screen = _run_taskfzf_in_pty(
        scratch_env,
        env_overrides={EnvVar.LIST_CHANGE: "context"},
        keys=["\x1b"],
    )
    assert marker.read_text().strip() == "rc.context=alpha", (
        f"cancelling the picker must leave the current filter alone; "
        f"marker={marker.read_text()!r} screen tail={screen[-300:]!r}"
    )
