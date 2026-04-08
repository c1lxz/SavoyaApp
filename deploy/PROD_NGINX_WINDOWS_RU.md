# Прод-запуск SavoyaApp через nginx на Windows

Этот вариант заменяет `npm run web` и dev-server фронтенда.

Что должно работать в проде:

- backend слушает только `127.0.0.1:8000`
- frontend собран в статические файлы `frontend/dist`
- `nginx` слушает `80` и отдаёт сайт
- `/api` и `/health` проксируются из `nginx` в backend

## 1. Подготовить backend

Заполните `.env` под прод:

```env
DEBUG=False
DOCS_ENABLED=False
DATABASE_URL=sqlite+aiosqlite:///./backend_prod.db
SECRET_KEY=CHANGE_ME
BOOTSTRAP_DEMO_USER=False
GATE_REAL_INTEGRATION_ENABLED=True
ALLOWED_HOSTS_JSON=["xn--80aaachc8cmu1au8c1f.xn--p1ai","127.0.0.1","localhost","testserver"]
CORS_ALLOW_ORIGINS_JSON=["http://xn--80aaachc8cmu1au8c1f.xn--p1ai","https://xn--80aaachc8cmu1au8c1f.xn--p1ai"]
```

Backend стартует так:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\start_backend.ps1
```

В проде backend не должен слушать `0.0.0.0`, только `127.0.0.1`.

## 2. Собрать frontend без dev-режима

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\publish_frontend.ps1
```

После этого должны появиться статические файлы в `frontend/dist`.

## 3. Подключить nginx

1. Установите Windows-версию `nginx`.
2. Скопируйте [savoyaapp-domain.conf](/e:/savoya/SavoyaApp/deploy/nginx/savoyaapp-domain.conf) в конфиг `nginx`.
3. Проверьте путь `root E:/savoya/SavoyaApp/frontend/dist;`.
4. Если проект лежит в другом каталоге, замените путь в `root`.
5. Проверьте конфиг:

```powershell
nginx -t
```

6. Перезапустите `nginx`:

```powershell
nginx -s reload
```

## 4. Проверка

Проверьте backend локально:

```powershell
curl http://127.0.0.1:8000/health
```

Проверьте через `nginx`:

```powershell
curl http://127.0.0.1/health
curl http://127.0.0.1/
```

Если DNS уже указывает на сервер, отдельно проверьте домен:

```powershell
curl http://xn--80aaachc8cmu1au8c1f.xn--p1ai/health
```

## 5. Что уже исправлено в backend под прод

- активные битые заявки с `gate_key_id <= 0` автоматически помечаются как `cancelled` на старте
- повторная активная заявка на тот же номер больше не создаётся
- на уровне БД создаётся partial unique index для активных `requests`
