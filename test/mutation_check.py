"""Prove the suite catches the bugs that actually shipped.

A green suite means nothing until you have seen it go red. Every bug in this
project's history survived a check that could not detect it, so this script
reintroduces each one and fails if the tests stay green.

Run:  python3 test/mutation_check.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (name, file, original snippet, broken replacement)
MUTATIONS = [
    (
        "final answer is never read",
        "adapters/claude-code.py",
        '    if text.strip():\n        vlib.speak_async(text, session=hook_input.get("session_id"))',
        "    if False:\n        pass",
    ),
    (
        "only the newest entry is read, so prose before a tool call is lost",
        "scripts/vlib.py",
        "        if _is_real_user_turn(entry):\n            return \"\"",
        "        if entry.get(\"type\") == \"assistant\":\n            return \"\"\n        if _is_real_user_turn(entry):\n            return \"\"",
    ),
    (
        "gives up before the transcript is flushed to disk",
        "adapters/claude-code.py",
        "    for attempt in range(6):",
        "    for attempt in range(1):",
    ),
    (
        "code blocks are read aloud",
        "scripts/vlib.py",
        '    t = re.sub(r"^[ \\t]*(```|~~~).*?^[ \\t]*\\1[ \\t]*$", " ", t, flags=re.S | re.M)',
        "    pass",
    ),
    (
        "speech continues after being turned off",
        "scripts/vlib.py",
        '    if not cfg.get("enabled", False):\n        return "disabled"',
        "    if False:\n        return \"disabled\"",
    ),
    (
        "the same answer is spoken twice",
        "scripts/vlib.py",
        "    if _is_repeat(clean):",
        "    if False and _is_repeat(clean):",
    ),
    (
        "playback never runs after synthesis",
        "scripts/vlib.py",
        "        subprocess.run(player + [str(wav)])",
        "        pass",
    ),
    (
        "a default change silences an existing install",
        "scripts/vlib.py",
        '    if "enabled" not in stored:\n        cfg["enabled"] = True',
        "    pass",
    ),
    (
        "one session cuts off another session's audio",
        "scripts/vlib.py",
        "    return _kill_marker(pid_file(session))",
        "    return any(_kill_marker(m) for m in RUN_DIR.glob('pid-*')) if RUN_DIR.is_dir() else False",
    ),
    (
        "Codex answers are dropped",
        "adapters/codex.py",
        '    text = event.get("last-assistant-message") or event.get("last_assistant_message")',
        "    text = None",
    ),
]


def run_suite(cwd):
    return subprocess.run(
        [sys.executable, str(Path(cwd) / "test" / "test_wiring.py")],
        cwd=cwd, capture_output=True, text=True, timeout=300,
    )


def main():
    baseline = run_suite(REPO)
    if baseline.returncode != 0:
        print("The suite is already failing; fix that before checking mutations.")
        print(baseline.stderr[-2000:])
        return 1

    print(f"Baseline green. Checking {len(MUTATIONS)} mutations.\n")
    undetected = []

    for name, rel, original, broken in MUTATIONS:
        work = Path(tempfile.mkdtemp(prefix="agent-voice-mutation-"))
        clone = work / "repo"
        shutil.copytree(REPO, clone, ignore=shutil.ignore_patterns(".git", "__pycache__"))

        target = clone / rel
        source = target.read_text()
        if original not in source:
            print(f"  SKIP  {name}\n        (snippet not found in {rel} — mutation is stale)")
            undetected.append(f"{name} (stale)")
            shutil.rmtree(work, ignore_errors=True)
            continue

        target.write_text(source.replace(original, broken, 1))
        result = run_suite(clone)
        caught = result.returncode != 0
        print(f"  {'CAUGHT' if caught else 'MISSED'}  {name}")
        if not caught:
            undetected.append(name)
        shutil.rmtree(work, ignore_errors=True)

    print()
    if undetected:
        print(f"{len(undetected)} mutation(s) went undetected:")
        for u in undetected:
            print(f"  - {u}")
        return 1
    print("Every historical bug is caught by the suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
