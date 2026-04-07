# Подключение Домена `шлагбаумсавоя.рф`

Текущий punycode домена:

```text
xn--80aaachc8cmu1au8c1f.xn--p1ai
```

Он уже используется в:

- `frontend/nginx.conf`
- `deploy/nginx/nginx-ip-only.conf`
- `docker-compose.yml`
- `backend/app/config.py`

## Что обязательно нужно сделать на сервере

1. Настроить DNS-запись `A` для `шлагбаумсавоя.рф` на внешний IP сервера.
2. Если есть `www`, либо добавить отдельную запись, либо сделать редирект.
3. Открыть на сервере порт `80`, а позже и `443`.
4. Поднять приложение так, чтобы Nginx слушал `0.0.0.0:80`.

## Проверка DNS

С другого хоста:

```powershell
nslookup шлагбаумсавоя.рф
```

Или:

```powershell
ping шлагбаумсавоя.рф
```

IP должен совпадать с публичным IP вашего сервера.

## Запуск через Docker

Из корня проекта:

```powershell
docker compose up --build -d
```

Проверка контейнеров:

```powershell
docker compose ps
```

Проверка backend:

```powershell
curl http://127.0.0.1:8000/health
```

Проверка frontend через локальный Nginx:

```powershell
curl http://127.0.0.1/
```

## Если домен все еще не открывается

Проверьте по порядку:

1. Домен действительно указывает на ваш сервер.
2. Порт `80` не блокируется провайдером, роутером или Windows Firewall.
3. Nginx/контейнер frontend реально запущен и слушает `80`.
4. На сервере нет другого веб-сервера, уже занявшего порт `80`.
5. Если используется HTTPS, нужен отдельный TLS-конфиг и сертификат.

## Что уже сделано в коде

- Backend разрешает домен в `ALLOWED_HOSTS_JSON`.
- Backend разрешает `http` и `https` origin домена в `CORS_ALLOW_ORIGINS_JSON`.
- Frontend Nginx настроен на `server_name xn--80aaachc8cmu1au8c1f.xn--p1ai`.
- `/api` и `/health` проксируются на backend.
