# Домен и следующий этап Gate/Wiegand

## 1. Что уже видно по домену

На 2026-04-09 домен `шлагбаумсавоя.рф` уже делегирован на `ns1.reg.ru` и `ns2.reg.ru`, но его `A`-запись резолвится в `198.18.1.102`.

Это плохой признак: диапазон `198.18.0.0/15` зарезервирован под тестовые сети и не должен использоваться как публичный IP сайта. Если у вас в DNS реально стоит `198.18.1.102`, сайт не заработает ни от правок backend, ни от Nginx, пока запись не будет заменена на настоящий внешний IP сервера.

## 2. Что проверить в REG.RU

1. Откройте карточку домена в REG.RU.
2. Убедитесь, что домен делегирован именно на DNS-серверы REG.RU, а не на сторонние NS.
3. Откройте раздел управления DNS-зоной.
4. Проверьте корневую запись `@`.
5. Для `@` должна быть запись `A`, указывающая на реальный белый IP сервера.
6. Если там стоит `198.18.1.102`, удалите её и создайте правильную `A`-запись.
7. Если нужен `www`, добавьте `CNAME` для `www -> xn--80aaachc8cmu1au8c1f.xn--p1ai` или отдельную `A`-запись на тот же IP.
8. Если меняли NS недавно, дождитесь перепропагации.
9. Если сервер за роутером, проверьте проброс порта `80` на Windows-сервер.
10. Проверьте, что Windows Firewall пропускает вход на `80`, а позже и на `443`.

## 3. Что должно быть на сервере

1. Backend должен слушать `127.0.0.1:8000`.
2. Nginx должен слушать `0.0.0.0:80`.
3. В `deploy/nginx/savoyaapp-domain.conf` корень сайта должен указывать на собранный `frontend/dist`.
4. Frontend должен быть пересобран командой из `deploy/windows/publish_frontend.ps1`.
5. Backend должен запускаться через `deploy/windows/start_backend.ps1`.

## 4. Безопасные PowerShell-команды для следующего этапа Wiegand/TCP

Эти команды не должны физически открыть шлагбаум, если не переводить `GATE_WIEGAND_TRANSPORT` из `dry_run` в `tcp`.

### DNS/HTTP

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_domain_setup.ps1
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
Resolve-DnsName 192.168.0.65
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

## 5. Что переключать только потом

Пока диагностика не закончена, оставляйте:

```env
GATE_WIEGAND_TRANSPORT=dry_run
GATE_WIEGAND_TCP_HOST=192.168.0.65
GATE_WIEGAND_TCP_PORT=5000
```

Только после проверки формата полезной нагрузки и подтверждения сетевого тракта можно временно переключать `GATE_WIEGAND_TRANSPORT=tcp`.
