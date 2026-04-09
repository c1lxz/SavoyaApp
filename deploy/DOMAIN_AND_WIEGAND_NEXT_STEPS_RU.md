# Домен, HTTPS и следующий этап Gate/Wiegand

## Что уже подтверждено

- Домен `шлагбаумсавоя.рф` резолвится в `185.245.187.125`.
- На сервере backend отвечает на `127.0.0.1:8000/health`.
- `nginx` уже умеет проксировать `/health` и `/api`.
- В проекте есть файлы сертификата: [`certificate.crt`](../certificate.crt) и [`certificate.key`](../certificate.key).
- Сертификат выдан на `www.xn--80aaachc8cmu1au8c1f.xn--p1ai` и содержит SAN для `xn--80aaachc8cmu1au8c1f.xn--p1ai` и `www.xn--80aaachc8cmu1au8c1f.xn--p1ai`.

## Важное ограничение

Пока HTTPS не подключён в `nginx`, домен должен работать только по `http`. Снаружи у тебя сейчас именно сетевой уровень отделяет доступ от рабочего backend.

## Безопасный план включения HTTPS

1. Оставить backend как есть: `127.0.0.1:8000`.
2. Положить `certificate.crt` и `certificate.key` в доступное nginx место на сервере.
3. Включить в `nginx` два server block:
   - `80` с редиректом на `https://$host$request_uri`
   - `443 ssl` с проксированием `/health` и `/api`
4. Проверить конфиг только командой `nginx -t`.
5. Проверить локально `http://127.0.0.1/health` и `https://127.0.0.1/health -SkipCertificateCheck`.
6. Только после этого открывать/проверять внешний доступ с другого устройства.

## Рекомендуемый nginx-конфиг для Windows

Ниже шаблон. На сервере замени пути на фактические пути своей установки.

```nginx
worker_processes 1;

events {
    worker_connections 1024;
}

http {
    include mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 30;
    server_tokens off;
    client_max_body_size 2m;

    upstream savoya_backend {
        server 127.0.0.1:8000;
        keepalive 16;
    }

    server {
        listen 80 default_server;
        server_name xn--80aaachc8cmu1au8c1f.xn--p1ai _;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl default_server;
        server_name xn--80aaachc8cmu1au8c1f.xn--p1ai _;

        ssl_certificate     C:/Users/User/Desktop/SavoyaApp/SavoyaApp/certificate.crt;
        ssl_certificate_key C:/Users/User/Desktop/SavoyaApp/SavoyaApp/certificate.key;

        root C:/Users/User/Desktop/SavoyaApp/SavoyaApp/frontend/dist;
        index index.html;

        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

        location /api/ {
            proxy_pass http://savoya_backend/api/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_send_timeout 30s;
            proxy_read_timeout 30s;
        }

        location ~ ^/(auth|user|passes|gates|access|requests)(/|$) {
            proxy_pass http://savoya_backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_send_timeout 30s;
            proxy_read_timeout 30s;
        }

        location = /health {
            proxy_pass http://savoya_backend/health;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        location / {
            try_files $uri $uri/ /index.html;
        }
    }
}
```

Если на сервере проект лежит не в `C:/Users/User/Desktop/SavoyaApp/SavoyaApp`, а в другом месте, меняй только `ssl_certificate`, `ssl_certificate_key` и `root`.

## Команды проверки

Все команды ниже безопасны: они только читают состояние.

```powershell
Get-ChildItem . -File | Where-Object { $_.Name -match '^certificate\.(crt|key)$' }
certutil -dump certificate.crt
Get-Content certificate.key -TotalCount 5
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 80,443,8000 } | Format-Table -AutoSize
```

Ожидаемый результат:
- `certificate.crt` есть один блок `BEGIN CERTIFICATE`
- `certificate.key` начинается с `BEGIN RSA PRIVATE KEY`
- `nginx` слушает `80` и `443`
- backend слушает `8000`

Проверка после правки конфига:

```powershell
cd C:\Users\User\Downloads\nginx-1.29.8
.\nginx.exe -t
curl http://127.0.0.1/health
curl https://127.0.0.1/health -SkipCertificateCheck
curl https://127.0.0.1/api/gate/access-points -SkipCertificateCheck
```

Если `https://127.0.0.1/health` отвечает, значит сертификат и TLS-конфиг в порядке. Если браузер потом ругается на цепочку сертификатов, значит нужен intermediate/fullchain от CA, а не правка backend.

## Что уже готово для следующего этапа Gate/Wiegand

- `py -3.12-32 backend\app\scripts\gate_bridge.py get_access_points "{}"` уже работает.
- `pyodbc` и MDB-драйвер на машине есть.
- `GATE_WIEGAND_TRANSPORT=dry_run` оставлен безопасным.
- `GATE_WIEGAND_TCP_HOST=192.168.0.65` и `GATE_WIEGAND_TCP_PORT=5000` уже подготовлены.

## Безопасные команды для Wiegand-диагностики

```powershell
Get-Content .env | Select-String "GATE_WIEGAND_"
Get-Content backend\app\scripts\gate_runtime.py | Select-String "_send_wiegand26|payload_format|GATE_WIEGAND_TCP"
Test-NetConnection 192.168.0.65 -Port 5000
py -3.12-32 backend\app\scripts\gate_bridge.py get_access_points '{}'
py -3.12-32 backend\app\scripts\gate_bridge.py get_wiegand_credentials '{"external_key_id":"123"}'
```

Ни одна из этих команд не открывает проход физически. Они только читают конфиг, сеть и уже существующие данные Gate.
