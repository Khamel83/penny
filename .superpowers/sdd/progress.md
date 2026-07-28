Task 1: complete (commits 94e8fb0..cac7437, review clean)
Task 2: complete (commits cac7437..0d2be9b, review clean)
Task 3: complete (commits 0d2be9b..f4a8755, review clean)
Task 4: complete (commits f4a8755..e6384ed, review clean)

Task 6 repair: complete
- Scope: update the stale SQLite leak regression to patch the shared
  `watcher.transcribe_with_quality` seam while asserting it is not called for
  an already-known audio hash.
- Focused command/result: `/Users/macmini/penny/venv/bin/python3 -m pytest -q
  tests/test_sqlite_leak.py::SQLiteConnectionLeakTests::test_process_audio_file_links_already_logged_voice_memo`
  -> 1 passed.
- Full command/result: `/Users/macmini/penny/venv/bin/python3 -m pytest`
  -> 194 passed, 2 skipped.
- Pre-repair SHA: e6384ed.
