# HTTPS для шлагбаумсавоя.рф

Домен в `punycode`:

```text
xn--80aaachc8cmu1au8c1f.xn--p1ai
```

В репозитории уже есть сертификат и ключ:

- `certificate.crt`
- `certificate.key`

Проверка локального сертификата показала:

- сертификат валиден с `2026-04-08 18:30` до `2026-10-24 18:30`
- SAN содержит `xn--80aaachc8cmu1au8c1f.xn--p1ai` и `www.xn--80aaachc8cmu1au8c1f.xn--p1ai`

## Что уже изменено в проекте

- [`deploy/nginx/savoyaapp-domain.conf`](E:/savoya/SavoyaApp/deploy/nginx/savoyaapp-domain.conf) теперь поднимает:
  - `80` с редиректом на `https`
  - `443 ssl http2` для фронтенда и прокси на backend
- [`frontend/nginx.conf`](E:/savoya/SavoyaApp/frontend/nginx.conf) переведён на тот же сценарий для Docker-контейнера
- [`docker-compose.yml`](E:/savoya/SavoyaApp/docker-compose.yml) теперь публикует `443` и монтирует сертификаты в контейнер frontend
- [`backend/app/config.py`](E:/savoya/SavoyaApp/backend/app/config.py) и [`docker-compose.yml`](E:/savoya/SavoyaApp/docker-compose.yml) разрешают и `www`, и основной домен

## Что нужно поменять руками

Если используешь nginx на Windows-хосте:

1. Проверь путь к проекту.
2. Если проект лежит не в `E:/savoya/SavoyaApp`, поправь в [`deploy/nginx/savoyaapp-domain.conf`](E:/savoya/SavoyaApp/deploy/nginx/savoyaapp-domain.conf):
   - `ssl_certificate`
   - `ssl_certificate_key`
   - `root`
3. Скопируй этот конфиг в рабочий `nginx.conf` или подключи его через `include`.

Если используешь Docker Compose:

1. Убедись, что рядом с [`docker-compose.yml`](E:/savoya/SavoyaApp/docker-compose.yml) лежат `certificate.crt` и `certificate.key`.
2. Запусти:

```powershell
docker compose up --build -d
```

## Что обязательно должно быть вне кода

1. DNS `A`-запись для `шлагбаумсавоя.рф` должна указывать на внешний IP сервера.
2. Если нужен `www`, для `www.шлагбаумсавоя.рф` тоже должна быть DNS-запись.
3. На сервере должны быть открыты порты `80` и `443`.
4. Backend должен быть доступен локально на `127.0.0.1:8000`.

## Проверка на сервере

Проверка backend:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Проверка конфига nginx:

```powershell
nginx -t
```

Перезагрузка nginx:

```powershell
nginx -s reload
```

Проверка HTTP -> HTTPS:

```powershell
curl.exe -I http://xn--80aaachc8cmu1au8c1f.xn--p1ai/health
```

Проверка HTTPS:

```powershell
curl.exe https://xn--80aaachc8cmu1au8c1f.xn--p1ai/health
```

Локальная проверка по IP/loopback, если сертификат не совпадает с именем хоста:

```powershell
curl.exe -k https://127.0.0.1/health
```

## Важный нюанс по цепочке сертификатов

Сейчас конфиг использует `certificate.crt` как `ssl_certificate`. Это сработает, если файл уже содержит полную цепочку.

Если браузер покажет ошибку недоверенной цепочки, нужно заменить `certificate.crt` на fullchain-файл:

1. взять intermediate сертификат у CA
2. склеить `server cert + intermediate`
3. указать этот итоговый файл в `ssl_certificate`

Ключ `certificate.key` менять не нужно.
