# Appendix: Background for the Memory Lessons

> **Goal:** everything that isn't about memory itself but is needed to follow it: the `lab` files in full, what pytest is, who writes the `calc:` message, and Claude Code's built-in tools.
> **Part of:** [Lesson 02: Memory](02-memory.md). Read the core lesson first; it introduces the `lab` project used here.

---

### Every file, in full

Each file below is shown exactly as it is on disk; nothing is added inside the blocks. Read the one line under each block for what it does.

`~/lab/calc.py`, the calculator:

```python
def add(a, b):
    return a + b


def divide(a, b):
    return a / b


def average(nums):
    return sum(nums) / len(nums)
```

Three functions: `add` adds two numbers, `divide` divides `a` by `b`, `average` adds a list of numbers and divides by how many there are. Note that `divide(1, 0)` crashes, which is why later lessons fix it.

`~/lab/tests/test_calc.py`, the checks that pytest runs (explained in "What pytest is" below):

```python
from calc import add, divide


def test_add():
    assert add(2, 3) == 5


def test_divide():
    assert divide(6, 3) == 2
```

Two checks: "add 2 and 3 gives 5" and "divide 6 by 3 gives 2".

`~/lab/CLAUDE.md` ★:

```markdown
# Lab project

- Run tests with: `python3 -m pytest -q`
- Every function needs type hints.
- Conventions: @docs/conventions.md
```

Two rules, and a line that imports the next file.

`~/lab/docs/conventions.md` ★:

```markdown
# Conventions

- Error messages start with the prefix `calc:`.
```

One rule. It loads only because `CLAUDE.md` points to it with `@`.

`~/lab/.claude/rules/tests.md` ★:

```markdown
---
paths:
  - "tests/**/*.py"
---

# Test rules

- Test function names must start with `test_lab_`.
```

The part between the two `---` lines is settings for this rule (`paths:` = which files it applies to); the rest is the rule itself.

`~/lab-logs/il-settings.json`, logger 1 (explained in Step 2):

```json
{
  "hooks": {
    "InstructionsLoaded": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "jq -c '{file: .file_path, memory_type, load_reason}' >> /tmp/il.log"
          }
        ]
      }
    ]
  }
}
```

What the `command` does (JSON allows no comments, so the notes are here):

```text
jq -c '{file: .file_path, memory_type, load_reason}'   ← jq reads the hook's JSON input; keep these 3 fields; -c = on one line
>> /tmp/il.log                                          ← add that line to the end of /tmp/il.log
```

Every time a memory file loads, write one line about it to `/tmp/il.log`.

`~/lab-logs/order-settings.json`, logger 2 (explained in "Second: how to read the log"):

```json
{
  "hooks": {
    "InstructionsLoaded": [{"hooks": [{"type": "command",
      "command": "jq -r '\"LOADED  \" + .file_path + \"  (\" + .load_reason + \")\"' >> /tmp/order.log"}]}],
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "jq -r '\"BEFORE  \" + .tool_name + \" \" + (.tool_input.file_path // .tool_input.command // \"\")' >> /tmp/order.log"}]}],
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command",
      "command": "jq -r '\"AFTER   \" + .tool_name + \" \" + (.tool_input.file_path // .tool_input.command // \"\")' >> /tmp/order.log"}]}]
  }
}
```

What the commands do (JSON allows no comments, so the notes are here):

```text
"matcher": "*"                                       ← run for every tool
jq -r '"BEFORE  " + .tool_name + " " + …'            ← jq builds one text line from the hook's JSON input; -r = plain text, no quotes
.tool_input.file_path // .tool_input.command // ""   ← the file path; if there is none, the command; if neither, nothing
>> /tmp/order.log                                    ← add the line to the end of /tmp/order.log
```

Same idea, but also writes a line just before (`BEFORE`) and just after (`AFTER`) every tool call, all into `/tmp/order.log`.

| File (full path) | Has `paths:`? | Applies to | Can Claude Code decide at session start? |
|------------------|---------------|------------|-------------------------------------------|
| `~/lab/CLAUDE.md` | No | Everything | ✅ Yes, it always applies |
| `~/lab/docs/conventions.md` | No (imported by `CLAUDE.md`) | Everything | ✅ Yes, it comes with `CLAUDE.md` |
| `~/lab/.claude/rules/tests.md` | `tests/**/*.py` | Only test files | ❌ No: no file has been touched yet |

Paths in the rest of this section, such as `tests/test_calc.py`, are relative to `~/lab/`, so `tests/test_calc.py` means `~/lab/tests/test_calc.py`. The pattern `tests/**/*.py` is relative to `~/lab/` too: any `.py` file anywhere under `~/lab/tests/`. `**` means any number of folders, **including zero**:

| Path | Folders between `tests/` and the file | Matches `tests/**/*.py`? |
|------|---------------------------------------|--------------------------|
| `tests/test_calc.py` | none (`**` = zero folders) | ✅ (this is the only test file in `lab`) |
| `tests/unit/test_x.py` | 1 | ✅ |
| `calc.py` | not under `tests/` | ❌ |
| `tests/notes.md` | none, but not `.py` | ❌ |

### What pytest is: a real run

**pytest** is an ordinary program (no AI) that runs **checks** on code. Think of a checklist inspector: you write down checks like "add 2 and 3, expect 5"; the inspector tries each one and reports pass or fail.

It finds checks by name: in files named `test_*.py`, every function named `test_*` is one check. `lab` has one such file, `~/lab/tests/test_calc.py`, with two checks (the `#` comments were added for this page):

```python
from calc import add, divide        # use the calculator's functions


def test_add():                     # check 1
    assert add(2, 3) == 5           # assert = "this must be true": add(2, 3) must give 5


def test_divide():                  # check 2
    assert divide(6, 3) == 2        # divide(6, 3) must give 2
```

Running it in `~/lab` **(recorded)**:

```bash
python3 -m pytest -q   # run every check; -q = short output
```

```text
..                                                                       [100%]
2 passed in 0.00s
```

| Mark | Means |
|------|-------|
| `.` | One check passed (two dots = two checks) |
| `F` | One check failed |
| `[100%]` | Progress: all checks have run |
| `2 passed` | The summary |

Now the same run after **deliberately breaking** `add` in a copy of `lab` (it subtracts instead of adding) **(recorded)**:

```text
F.                                                                       [100%]
=================================== FAILURES ===================================
___________________________________ test_add ___________________________________

    def test_add():
>       assert add(2, 3) == 5          ← the check that failed
E       assert -1 == 5                 ← it got -1, but expected 5
E        +  where -1 = add(2, 3)

tests/test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED tests/test_calc.py::test_add - assert -1 == 5
1 failed, 1 passed in 0.01s
```

That's why `CLAUDE.md` names the command: after changing code, Claude runs it to check it didn't break anything. In [Lesson 09](09-advanced-features.md), Claude ran `python3 -m pytest -q` twice this way.

### Who writes `calc: cannot divide by zero`? Not an LLM at run time

The message is produced in three moments, and **Claude is involved only in the second**:

| Moment | Who | What happens |
|--------|-----|--------------|
| 1. Before any session | You | You write the rule as plain text in `docs/conventions.md` |
| 2. While Claude edits code | **Claude (the LLM)** | It reads the rule from memory and **types the message into `calc.py`** |
| 3. Any time the program runs, later | **Python only** | It prints the text stored in `calc.py`. No AI is called |

Moment 2, the real edit Claude made in [Lesson 09](09-advanced-features.md) (`acceptEdits` run) **(recorded)**:

```text
--- before:
def divide(a, b):
    return a / b

--- after:
def divide(a: float, b: float) -> float:                 ← type hints (CLAUDE.md rule)
    if b == 0:                                           ← if the divisor is zero…
        raise ValueError("calc: cannot divide by zero")  ← …stop with this message (conventions.md rule)
    return a / b
```

Moment 3, running `divide(1, 0)` on that code with plain Python **(recorded)**:

```text
  File ".../calc.py", line 7, in divide
    raise ValueError("calc: cannot divide by zero")
ValueError: calc: cannot divide by zero
```

The message is fixed text saved in the file, the same every time the program runs. The rule only shaped **what Claude wrote**.

In the same run, Claude also added a third check *before* fixing the code: "dividing by zero must stop with a message starting `calc:`". pytest shows the order **(recorded)**:

| | `calc.py` | pytest result |
|---|-----------|---------------|
| New check added, code not fixed yet | Still `return a / b` | `..F` → `1 failed, 2 passed` (got `ZeroDivisionError`) |
| After Claude's fix | The new code above | `...` → `3 passed` |

---

## Claude Code's built-in tools

**Are `Read`, `Bash` and `Write` on the same level? Yes.** All three are **built-in tools**, called the same way: Claude asks for a tool, Claude Code runs it, the result goes back to Claude. The same hooks fire for each (that's why every call below shows up as a `BEFORE`/`AFTER` pair), and the same permission system decides whether it may run. They differ only in what they act on:

| | `Read` | `Write` | `Bash` |
|---|---|---|---|
| Acts on | One file (reads it) | One file (creates or replaces it) | Anything a shell command can do |
| How the file appears in its input | `file_path` field | `file_path` field | Inside the command text (`cat tests/test_calc.py`) |
| Asks permission in Manual mode? | No (inside the project folder) | Yes | Yes, except a built-in set of read-only commands |

**What "anything a shell command can do" looks like.** `Bash` runs a command **as you**, in your terminal: it can use every command-line tool installed on your machine, signed in with **your** accounts (`aws configure`, `az login`, `gcloud auth login`, `gh auth login`). If a command works when you type it, Claude can run it, and nothing more. Examples, grouped by what the command acts on (example commands, not recorded runs; names like `my-bucket` are placeholders):

| Acts on | Example command | What Claude would use it for |
|---------|-----------------|------------------------------|
| 📁 Files and folders | `find . -name "*.log" -mtime +7` | Find log files older than 7 days |
| | `mv old_name.py new_name.py` | Rename a file |
| 🧪 Your code: run, build, test | `python3 -m pytest -q` | Run the tests (as in this lesson) |
| | `npm run build` | Build a web app |
| 📦 Installed software | `pip install requests` · `npm install lodash` · `brew install jq` | Add a library or tool |
| 🌿 Version control (local) | `git status` · `git diff` · `git commit -m "fix: zero check"` | See and save changes |
| 🐙 Code hosting | `gh pr create --title "Fix divide" --body "Adds zero check"` | Open a pull request on GitHub |
| | `gh run list --limit 5` | Check the latest CI runs |
| 🌐 Any web API | `curl -s https://api.github.com/repos/anthropics/claude-code` | Call an HTTP API and read the JSON |
| ☁️ AWS | `aws s3 ls s3://my-bucket/reports/` | List files in an S3 bucket |
| | `aws stepfunctions start-execution --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:OrderFlow --input '{"orderId":"A-17"}'` | **Start a Step Functions state machine** run |
| | `aws stepfunctions describe-execution --execution-arn <arn-from-the-output-above>` | Check whether that run succeeded |
| | `aws logs tail /aws/lambda/order-handler --since 10m` | Read the last 10 minutes of a Lambda's logs |
| ☁️ Azure | `az group list -o table` | List resource groups |
| | `az webapp restart --name my-app --resource-group my-rg` | Restart a web app |
| ☁️ Google Cloud | `gcloud run deploy my-service --source . --region us-central1` | Deploy to Cloud Run |
| 🐳 Containers | `docker build -t myapp .` · `docker ps` | Build an image / list running containers |
| | `kubectl get pods -n prod` · `kubectl logs deploy/api -n prod --tail=50` | Check a Kubernetes cluster |
| 🏗️ Infrastructure as code | `terraform plan` | Preview infrastructure changes |
| 🗄️ Databases | `psql "$DATABASE_URL" -c "select count(*) from orders;"` | Query a PostgreSQL database |
| | `sqlite3 app.db ".tables"` | List tables in a SQLite file |
| 🖥️ Your computer | `lsof -i :3000` · `df -h` | Which program uses port 3000 / free disk space |

In the tool call, the command is just text in the `command` field. This is the real input of a `Bash` call recorded in [Lesson 06](06-hooks.md) (trimmed):

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "ls 06-hooks | head -3",
    "description": "List first three entries in 06-hooks"
  }
}
```

The `aws stepfunctions start-execution …` above would arrive the same way, with that text in `command`.

**Why this matters:** cloud and database commands change **real** things with your credentials. Claude Code asks before each one in Manual mode, and you can set rules per command, using the same `Bash(…)` form as `--allowedTools` ([Lesson 09](09-advanced-features.md)), or a guard hook ([Lesson 06](06-hooks.md)):

```json
{
  "permissions": {
    "allow": ["Bash(aws stepfunctions describe-execution:*)", "Bash(kubectl get:*)"],
    "deny":  ["Bash(terraform apply:*)", "Bash(kubectl delete:*)"]
  }
}
```

What these rules do (JSON allows no comments, so the notes are here):

```text
"allow": [...]   ← run these without asking: read-only checks (describe an execution, list pods)
"deny":  [...]   ← never run these: they change or delete real infrastructure
:*               ← "followed by anything", e.g. any arguments after "kubectl get"
```

The basic built-in tools, grouped by job **(docs)**:

| Job | Tool | What it does | Asks permission? |
|-----|------|--------------|------------------|
| 📄 Files | `Read` | Read a file | No |
| | `Write` | Create or overwrite a file | Yes |
| | `Edit` | Change part of a file | Yes |
| | `Glob` | Find files by name pattern | No |
| | `Grep` | Search inside files | No |
| | `NotebookEdit` | Change a Jupyter notebook cell | Yes |
| 💻 Commands | `Bash` | Run a shell command | Yes (read-only commands excepted) |
| | `PowerShell` | Run a PowerShell command (Windows) | Yes |
| | `Monitor` | Run a command in the background and react to each output line | Yes |
| 🌐 Web | `WebFetch` | Fetch a web page | Yes |
| | `WebSearch` | Search the web | Yes |
| 🤝 Helpers | `Agent` | Start a subagent ([Lesson 04](04-subagents.md)) | No |
| | `Skill` | Run a skill ([Lesson 03](03-skills.md)) | Yes |
| | `AskUserQuestion` | Ask you a multiple-choice question | No |
| 🗺️ Planning | `EnterPlanMode` / `ExitPlanMode` | Switch into plan mode / present the plan ([Lesson 09](09-advanced-features.md)) | No / Yes |
| | `TaskCreate`, `TaskList`, `TaskUpdate`, `TaskGet` | Keep a task checklist (only on some models by default) | No |
| 🔌 MCP | `ListMcpResourcesTool`, `ReadMcpResourceTool` | List / read MCP resources ([Lesson 05](05-mcp.md)) | No |
| | `ToolSearch` | Load MCP tools that were held back until needed | No |

"Asks permission?" is for Manual mode, on paths inside the working folder. The docs note that `Glob` and `Grep` are absent by default on macOS, Linux and WSL (Claude then searches with `Bash`), though the recorded runs in [Lesson 04](04-subagents.md) on this machine did call `Grep`. There are about 45 built-in tools in all (scheduling, worktrees, messaging other agents, …); see the [official tools reference](https://code.claude.com/docs/en/tools-reference). Tools from MCP servers come on top of these, named `mcp__<server>__<tool>`.

---

← Back to [Lesson 02: Memory](02-memory.md)
