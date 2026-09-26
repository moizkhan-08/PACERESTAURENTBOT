# Rule: Universal Python File for Tasks and Testing

## Core Mandate
Whenever there is an executable task, diagnostic, verification, bug reproduction, script execution, or any testing required:
1. **Single Universal File:** Always use and maintain a single dedicated universal Python file: `universal_test.py` located at the project root.
2. **Never Create Scattered Test Scripts:** Strictly avoid creating ad-hoc, temporary, or scattered one-off test scripts (e.g. `test1.py`, `temp.py`, `check.py`, `test_run.py`, etc.).
3. **Write and Edit in Place:** Whenever a new task or test case needs to be run, write, modify, and edit `universal_test.py` directly.
4. **Autonomous Execution:** Execute tasks and tests directly via `python universal_test.py`. Keep test flows consolidated, reproducible, and clean in this single file.
