# Test Users

При старте backend с локальной SQLite-базой `backend_test_local.db` аккаунт `demo` создаётся автоматически, потому что в `.env` включён `BOOTSTRAP_DEMO_USER=True`.

Логины `user01`...`user05` не bootstrap'ятся кодом приложения: они работают только если уже присутствуют в локальной SQLite-базе или были добавлены отдельным сидированием.

| Login | Password |
| --- | --- |
| demo | demo123 |
| user01 | demo123 |
| user02 | demo123 |
| user03 | demo123 |
| user04 | demo123 |
| user05 | demo123 |
