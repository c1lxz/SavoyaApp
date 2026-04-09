# Домен и следующий этап Gate/Wiegand

## 1. Что уже видно по домену

На 2026-04-09 домен `шлагбаумсавоя.рф` уже делегирован на `ns1.reg.ru` и `ns2.reg.ru`, но его `A`-запись резолвится в `198.18.1.102`.

При этом реальный внешний IP сервера: `185.245.187.125`.

Значит проблема сейчас почти наверняка в DNS-зоне REG.RU: корневая `A`-запись домена указывает не на сервер, а на неверный адрес. Пока `A`-запись не будет указывать на `185.245.187.125`, сайт не заработает ни от правок backend, ни от Nginx.

## 2. Что именно должно быть в REG.RU

В DNS-зоне домена должны быть такие записи:

```text
@      A      185.245.187.125
www    CNAME  xn--80aaachc8cmu1au8c1f.xn--p1ai
```

Если `www` не нужен, можно не добавлять вторую запись.

Если сейчас для `@` стоит `198.18.1.102`, её нужно удалить и заменить на `185.245.187.125`.

## 3. Пошагово в REG.RU

1. Откройте личный кабинет REG.RU.
2. Перейдите в карточку домена `шлагбаумсавоя.рф`.
3. Проверьте, что домен использует DNS-серверы `ns1.reg.ru` и `ns2.reg.ru`.
4. Откройте раздел управления DNS-зоной.
5. Найдите запись типа `A` для хоста `@`.
6. Если там указан `198.18.1.102`, удалите эту запись.
7. Создайте новую запись `A`:
   `Хост`: `@`
   `Значение`: `185.245.187.125`
8. Сохраните изменения.
9. Если нужен `www`, создайте запись:
   `Тип`: `CNAME`
   `Хост`: `www`
   `Значение`: `xn--80aaachc8cmu1au8c1f.xn--p1ai`
10. Подождите обновления DNS.

## 4. Что проверить после замены A-записи

После обновления DNS команда ниже должна возвращать `185.245.187.125`:

```powershell
Resolve-DnsName xn--80aaachc8cmu1au8c1f.xn--p1ai -Type A
```

После этого проверьте:

```powershell
curl http://xn--80aaachc8cmu1au8c1f.xn--p1ai/health
```

Если DNS уже правильный, а сайт всё ещё не открывается, тогда проверять нужно уже сервер:

1. открыт ли входящий `80` на роутере или у провайдера,
2. открыт ли `80` в Windows Firewall,
3. слушает ли Nginx порт `80`,
4. поднят ли backend на `127.0.0.1:8000`.

## 5. Что должно быть на сервере

1. Backend должен слушать `127.0.0.1:8000`.
2. Nginx должен слушать `0.0.0.0:80`.
3. В `deploy/nginx/savoyaapp-domain.conf` корень сайта должен указывать на собранный `frontend/dist`.
4. Frontend должен быть пересобран командой из `deploy/windows/publish_frontend.ps1`.
5. Backend должен запускаться через `deploy/windows/start_backend.ps1`.

## 6. Безопасные PowerShell-команды для следующего этапа Wiegand/TCP

Эти команды не должны физически открыть шлагбаум, если не переводить `GATE_WIEGAND_TRANSPORT` из `dry_run` в `tcp`.

### DNS/HTTP

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_domain_setup.ps1 -ExpectedIp 185.245.187.125
Resolve-DnsName xn--80aaachc8cmu1au8c1f.xn--p1ai -Type A
Resolve-DnsName xn--80aaachc8cmu1au8c1f.xn--p1ai -Type NS
curl http://xn--80aaachc8cmu1au8c1f.xn--p1ai/health
```

### Локальный backend/Nginx

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1/health
curl http://127.0.0.1/api/gate/access-points
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 80,8000 }
```

### Проверка доступа до TCP-устройства без отправки Wiegand

```powershell
Test-NetConnection 192.168.0.65 -Port 5000
arp -a | findstr 192.168.0.65
route print
```

### Проверка текущих Wiegand-настроек приложения

```powershell
Get-Content .env | Select-String "GATE_WIEGAND_"
Get-Content backend\app\scripts\gate_runtime.py | Select-String "_send_wiegand26|payload_format|GATE_WIEGAND_TCP"
```

### Проверка реальных точек доступа Gate без открытия

```powershell
py -3.12 backend\app\scripts\gate_bridge.py get_access_points "{}"
py -3.12 backend\app\scripts\gate_bridge.py get_wiegand_credentials "{""external_key_id"":""123""}"
```

Вторая команда безопасна только как чтение. Она не открывает проход, а пытается вычислить Wiegand-представление для уже существующего ключа.

### Проверка, кто слушает порт 5000 на промежуточном сервисе

```powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 5000 } | Format-Table -AutoSize
Get-Process -Id (Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 5000 }).OwningProcess
```

## 7. Что переключать только потом

Пока диагностика не закончена, оставляйте:

```env
GATE_WIEGAND_TRANSPORT=dry_run
GATE_WIEGAND_TCP_HOST=192.168.0.65
GATE_WIEGAND_TCP_PORT=5000
```

Только после проверки формата полезной нагрузки и подтверждения сетевого тракта можно временно переключать `GATE_WIEGAND_TRANSPORT=tcp`.
