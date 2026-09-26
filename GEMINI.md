# Pace Restaurant AI WhatsApp Bot — Gemini & Antigravity Instructions

This project is governed by the dedicated architecture, design, and pattern guide located in:
👉 [AGENTS.md](AGENTS.md)

Please read and follow [AGENTS.md](AGENTS.md) for all project standards, operational shifts, 7-step ordering state machine, deterministic safety guards, database schemas, and testing workflows.

## 📌 Universal Task & Testing Rule
Whenever there is any executable task, diagnostic, verification, or testing to perform:
- **Mandatory Single File:** Always use and edit `universal_test.py` in the root directory.
- **No Scattered Scripts:** Never create random one-off scripts (e.g. `test1.py`, `temp.py`). All test and task execution logic must be written and edited directly in `universal_test.py`.

