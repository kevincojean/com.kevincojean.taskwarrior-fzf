# taskfzf ledger

## 2026-09-08 - T-010 baseline test suite design

### Discovery: dash rejects backticks inside double-quoted strings at parse time

**Context:** Writing `taskfzf-test.sh`; first draft failed with
`Syntax error: end of file unexpected` under dash. Bash parsed fine.

**Root cause:** dash implements POSIX strictly. Backticks inside
double-quoted strings ARE command substitution, same as outside quotes.
Unbalanced backticks become a parse error, not a runtime error.

**Concrete repro:**
```sh
todo "AC-11: A binding dispatches `task <id> append <args>`"
```
dash: `Syntax error: end of file unexpected`.
bash: runs fine.

**Fix:** don't use backticks for emphasis in shell strings. Use single
quotes (`'...'` inside `"..."`) or plain text. Backticks in `#`
comments are fine - the comment parser ignores them.

**Time cost:** ~3 iteration cycles of `dash -n` + bisect before
isolating. Worth recording because the same trap will hit any
test-suite message string that quotes a CLI invocation.

### Discovery: `?` is not a valid POSIX function name character

**Context:** `test_ac20_?_prints_keys()` failed with `Bad function
name` under dash.

**Root cause:** POSIX function names must match `[a-zA-Z_][a-zA-Z0-9_]*`.
`?` is not in that set. Bash allows more permissive names.

**Fix:** rename to `test_ac20_question_prints_keys()`. Document the
binding symbol (`?`) inside the function body in a comment, not in the
name.

**Lesson:** keep function names POSIX-strict even though the script
runs under bash on dev machines - CI / minimal containers use dash.

### Discovery: taskfzf README vs script disagree on T binding

**Context:** README lines 46 and 62 both list `T` as a binding, but
with different actions (`task edit` vs `task add`). The script binds
`T -> add` (line 267) and `E -> edit` (line 266).

**Decision:** the script is truth; the README has a duplicate entry
likely from drift. T-008 ("unbind this") in the kanban suggests this
overlap is a known issue. Test suite follows script behavior:
- AC-8 E -> edit
- AC-9 T -> add

### Decision: pure POSIX `/bin/sh` over bats for the test suite

**Context:** user asked why not bats. Four reasons specific to this
project:

1. Interpreter mismatch: `taskfzf` is `/bin/sh`. bats needs bash.
   Tests would run in bash, target runs in dash. Bugs like the two
   above would be masked.
2. Zero deps: `taskfzf-test.sh` must run on any host with `sh`,
   `task`, `fzf`. bats-core is an external install.
3. Scope: 23 tests, single-file project, ~280 lines under test.
   10-line `pass`/`fail`/`todo` helpers beat framework ceremony.
4. Deliverable: T-010 says "in a executable file called
   taskfzf-test.sh" - singular. bats wants a `*.bats` directory.

Decision recorded so future contributors don't re-litigate it.

### Decision: dropped ACs from initial draft (T-010 scope cut)

**Dropped entirely:**
- AC-2 (fzf version check) - would require mocking `fzf --version`
  which violates the no-mocking rule; user cut it.
- AC-23 (unwritable marker dir) - tests a path-dependency failure
  case, low signal. User cut it.
- AC-26 (context-with-dash bug info) - tests a workaround for
  upstream taskwarrior bug #2219. User cut it.

**Merged:**
- AC-27 (`_TASKFZF_SHOW=keys` standalone) -> folded into AC-20.
  Reason: `_TASKFZF_SHOW=keys` is an internal dispatch mechanism for
  the `?` binding (script line 277), not a user-facing entry point.
  Testing it separately tested implementation, not behavior. The
  useful assertion (the keys table actually renders) is now part of
  AC-20 alongside the grep check for the bind string.

**Final count:** 23 ACs across 6 groups (A:1, B:3, C:11, D:5, E:1, F:2).

### Plan file location

Approved plan: `.omo/plans/T-010-test-suite.md`. Reviewed by Momus,
verdict OKAY. Three implementation-time notes to address when bodies
are written:
1. Remove AC-2/23/26/27 functions and runner entries from the skeleton.
2. Add helpers `add_task`, `task_status`, `with_stdin_file`.
3. Create `$TESTDATA/xdgrun` and export `XDG_RUNTIME_DIR` in setup.

## 2026-09-08 - framework pivot: POSIX sh -> Python + pytest

User pushed back on the shell-based test suite ("absolutely
unmaintainable"). Pivot rationale:

- Test target (taskfzf) stays `/bin/sh`. Harness language is free.
- 23 tests with subprocess, env-var control, stdin feeding, scratch
  dirs - shell escaping made each test a 50-line dance of `$()` and
  `<<EOF` heredocs. Three separate debug sessions on parser quirks
  (backticks, `?` in names, `set -u` + line continuation) confirmed
  the harness language was the wrong tool.
- pytest gives real assertions, fixture-based setup/teardown,
  tracebacks pointing at the failing line, native `-v` output. Net
  file size dropped from ~280 lines of shell to ~250 lines of Python
  with stricter coverage.

**Deliverable changes:**
- `taskfzf-test.sh` (shell draft) deleted
- `taskfzf-test.py` created
- `pyproject.toml` created - pytest as `[project.optional-dependencies]
  test`, `requires-python = ">=3.10"`, `addopts = "-p no:libtmux"` to
  bypass a broken pytest plugin auto-registered in this env
- T-010.md amended `.sh` -> `.py`

**StrEnum usage (no string-driven-development):**
`EnvVar`, `Action`, `Binding` enums replace bare string literals for
env-var names, action verbs, and binding symbols. Test bodies use
`Action.DO` not `"do"`.

## 2026-09-08 - rename: test_ac* -> GivenWhenThen

User directed all 23 test functions to be renamed to BDD form:
`test_given_<state>_when_<action>_then_<outcome>`.

Per-AC traceability preserved via a single-line `# AC-N:` comment at
the top of each test body. Function bodies, fixtures, helpers,
StrEnums untouched. pytest result unchanged: 20 passed, 3 failed.

## 2026-09-08 - known-failing tests (real taskfzf bugs, deferred)

Three tests fail because `taskfzf` behaves differently than the
README documents or than the tests assert. Per agreement with user,
NOT fixing without explicit approval:

### Bug A (AC-20): literal `$` in keys table output

`taskfzf` lines 37-53 emit column separators with `$'\t'`
(ANSI-C quoting). `dash` doesn't expand `$'\t'`; it treats it as
literal `$\t`, then `echo` re-interprets `\t` as TAB. Net result:
every row gets a stray `$` prefix. Output starts `KEY $\tAction`
not `KEY\tAction`.

Fix in taskfzf: replace `$'\t'` with literal TAB or `printf '\t'`.

### Bug B (AC-22): two stacked bugs in non-numeric warning path

1. `case "$tasks_args" in ^[a-f0-9])` uses `^` as anchor. POSIX
   `case` patterns are glob syntax, not regex - `^` is a literal
   char. So the pattern never matches a non-numeric input.

2. `echo ---` between the action and `exit $?` resets `$?` to 0,
   so the script always exits 0 even when `task` returned non-zero.

Fix in taskfzf: (a) `[a-f0-9]*` not `^[a-f0-9]`; (b) capture exit
before the banner echo.

### Bug C (AC-25): multi-task warning in wrong if-branch

`taskfzf` lines 99-110 print "Only the first task" in the
SINGLE-token branch (`if [ "$tasks_args" = "${tasks_args%% *}" ]`).
Should be in the multi-token branch.

Fix in taskfzf: invert the condition.

## 2026-09-08 - harness issues hit and resolved during T-010 work

1. `libtmux` pytest plugin fatal on load in this env. Worked around
   via `addopts = "-p no:libtmux"`. Root cause unrelated to this
   project - pytest plugin ships an `@pytest.mark.skipif` on a
   fixture, which pytest 9 forbids.
2. taskwarrior urgency column padding broke exact stdout comparison
   for AC-3 / AC-5. Switched to `line.split()` whitespace-tokenized
   first-line match.
3. AC-10 taskrc syntax: plan's `context.mycontext.project=work`
   returns empty from `task _get rc.context.mycontext` on taskwarrior
   3.4.2. Working syntax is `context.mycontext=project:work`. Test
   uses working syntax with a `# NOTE` block explaining deviation.
4. AC-13 priority assertion: plan's substring `"priority H"` doesn't
   match `task list` output (priority is a single-letter column).
   Switched to `_task_field(env, tid, "priority") == "H"` for
   precision.

## 2026-09-08 - fzf binding syntax constraints

**Discovery: fzf 0.65.2 rejects `shift-X` keys with `unsupported key`**

**Context:** After binding `shift-c` as a context-change alias, fzf
exited with `unsupported key: shift-c` and produced no UI. Verified
empirically:
```sh
$ fzf --bind='shift-c:execute(echo hi)' </dev/null
unsupported key: shift-c
```

Checked every binding in the current set against fzf 0.65.2: D X u U
E a A M s S e R C ? ctrl-r ctrl-/ all accepted. Only `shift-c` was
rejected. `ctrl-/` and `ctrl-r` work fine - the `shift-` prefix is the
specific problem.

**Decision:** remove the `shift-c` binding. The existing `C` binding
already changes context, so the alias is redundant. Same rule applies
to any future `shift-X` binding - don't add them. Tested alt-/ctrl-/
ctrl-r syntax; only `shift-` is rejected.

**Test added:** `test_given_fzf_invoked_then_no_unknown_action_error`
now also asserts `"unsupported key" not in combined`. This catches
regressions if anyone re-adds `shift-X` (or any other unsupported
prefix) to BINDINGS_DATA.

**Time cost:** ~1 iteration once fzf's actual error message was
identified. Would have been longer without running fzf directly.

## 2026-09-08 - BINDINGS_DATA row format requires 4 columns

**Discovery:** the `_bindings_data_section` helper in taskfzf-test.py
parses rows with `line.split("|", 3)` - expecting 4 fields
(kind|key|arg|help). A row with only 3 fields raises `ValueError`
during the iteration. The original `show-info|enter|-|Show task
information` had 4 columns; my replacement `show-info|ctrl-/|Toggle
show task info` had 3 and crashed the test parser.

**Lesson:** keep the arg column even when the kind (show-info, undo,
reload, show-keys) doesn't use it. Use `-` as the placeholder, like
the original `show-info|enter|-|...` did. gen_bind_arg ignores the arg
column for these kinds but the BINDINGS_DATA parser doesn't.