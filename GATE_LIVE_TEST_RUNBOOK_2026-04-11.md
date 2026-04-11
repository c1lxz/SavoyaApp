# GATE Live Test Runbook — 2026-04-11

## Current backend state

- Branch: `main`
- Latest mapping fix: commit `80957ff`
- Real site action map:
  - `entry` -> `19` (`Камера Въезда`)
  - `exit` -> `20` (`Камера Выезда`)
  - `wicket_north` -> `15` (`Считыватель Северная калитка 1`)
  - `wicket_admin` -> `17` (`Считыватель калитка 1`)
  - `wicket_forest` -> `21` (`Вход Лес`)
  - `wicket_lake` -> `23` (`Вход озеро`)

## Current live-test transport in `.env`

- `GATE_WIEGAND_TRANSPORT=gateserv_tcp`
- `GATE_GATESERV_HOST=127.0.0.1`
- `GATE_GATESERV_PORT=1917`
- `GATE_GATESERV_PAYLOAD_FORMAT=frame_hex`
- `GATE_GATESERV_APPEND_NEWLINE=true`
- `DRY_RUN=false`

## Important limitation

- The backend is already opening the correct logical point.
- The remaining unknown is the exact payload that `GateServ` expects on `127.0.0.1:1917`.
- The current first hypothesis is:
  - `frame_hex` as text
  - with trailing newline
- A backend response with `success=true` only proves that bytes were sent to `GateServ`.
- Real confirmation is:
  - the physical point opened
  - and the logs changed in a way consistent with the attempt

## First live target

- Do not start with courier exit cleanup.
- First probe should be a point with a person physically standing next to it.
- Preferred first action:
  - `wicket_admin`
- Safe alternatives:
  - `wicket_north`
  - `wicket_forest`
  - `wicket_lake`

## Pre-flight

1. Restart the backend after the `.env` change.
2. Use a real resident account that can log into the app.
3. Have one observer at the exact gate/wicket being tested.
4. Before the first probe, capture the tail of the latest `TcpLog` and `PortLog`.

## Log capture commands

```powershell
$tcp = Get-ChildItem C:\GATE\Server\Log\TcpLog -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$tcp.FullName
Get-Content $tcp.FullName -Tail 20
```

```powershell
$port = Get-ChildItem C:\GATE\Server\Log\PortLog -File | Sort-Object LastWriteTime -Descending | Select-Object -First 20
$port[0].FullName
Get-Content $port[0].FullName -Tail 20
```

## Deterministic API flow

Examples below use direct backend access on `http://127.0.0.1:8000`.

If you test through Nginx, replace `$base` with your real public origin.

### 1. Login

```powershell
$base = "http://127.0.0.1:8000"
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" -Body '{"login":"YOUR_LOGIN","password":"YOUR_PASSWORD"}'
$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }
```

### 2. Create a temporary non-courier pass

```powershell
$car = "T" + (Get-Random -Minimum 10000 -Maximum 99999)
$expires = [DateTime]::UtcNow.AddHours(2).ToString("o")
$passBody = @{
  carNumber = $car
  plotNumber = "YOUR_PLOT"
  phoneNumber = "+79990000000"
  expiresAt = $expires
  isPermanent = $false
  isCourier = $false
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "$base/passes" -Headers $headers -ContentType "application/json" -Body $passBody
```

### 3. Confirm visible points

```powershell
Invoke-RestMethod -Method Get -Uri "$base/api/access/points/my" -Headers $headers
```

Expected point IDs for this site:

- `15`
- `17`
- `19`
- `20`
- `21`
- `23`

### 4. Send the first open probe

Start with `wicket_admin` unless another observed point is safer at the moment.

```powershell
Invoke-RestMethod -Method Post -Uri "$base/gates/open-action" -Headers $headers -ContentType "application/json" -Body '{"action":"wicket_admin"}'
```

Possible action values:

- `entry`
- `exit`
- `wicket_north`
- `wicket_admin`
- `wicket_forest`
- `wicket_lake`

### 5. Fetch the last event with transport details

```powershell
(Invoke-RestMethod -Method Get -Uri "$base/api/access/events/my" -Headers $headers) | Select-Object -First 1 | ConvertTo-Json -Depth 8
```

The key fields to inspect are:

- `status`
- `error_code`
- `error_message`
- `details.gate_result.transport`
- `details.gate_result.packet`
- `details.gate_result.wire`
- `details.gate_result.transport_error`

## Interpreting the first attempt

### Good result

All three are true:

- observer confirms physical opening
- API result says `success=true`
- the event has `transport = gateserv_tcp`

If that happens, the current `frame_hex` hypothesis is good enough to continue with broader validation.

### Partial result

- API says `success=true`
- `TcpLog` shows a new `Connection accepted` / `Connection closed`
- but the point did not open

This means:

- backend routing is correct
- GateServ accepted the TCP client
- but the payload format is still likely wrong

### Bad result

- API says `success=false`
- or event has `transport_error`

This means:

- the problem is transport-level first
- do not continue to payload changes until transport is clean

## Payload fallback order

If the first `frame_hex` probe does not produce a real opening, test formats in this exact order:

1. `payload_hex_be`
2. `raw_bytes`
3. `json`

For each switch:

1. change `.env`
2. restart backend
3. repeat one open probe on the same observed point
4. collect event JSON and the last 20 lines of `TcpLog` and `PortLog`

### Switch to `payload_hex_be`

```powershell
(Get-Content .env) -replace '^GATE_GATESERV_PAYLOAD_FORMAT=.*','GATE_GATESERV_PAYLOAD_FORMAT=payload_hex_be' | Set-Content .env
```

### Switch to `raw_bytes`

```powershell
(Get-Content .env) -replace '^GATE_GATESERV_PAYLOAD_FORMAT=.*','GATE_GATESERV_PAYLOAD_FORMAT=raw_bytes' | Set-Content .env
```

### Switch to `json`

```powershell
(Get-Content .env) -replace '^GATE_GATESERV_PAYLOAD_FORMAT=.*','GATE_GATESERV_PAYLOAD_FORMAT=json' | Set-Content .env
```

## What to bring into the next chat

For the exact attempt that matters, bring these 5 things:

1. the JSON returned by `/gates/open-action`
2. the JSON returned by `/api/access/events/my` for the latest event
3. the last 20 lines of the latest `TcpLog`
4. the last 20 lines of the latest `PortLog`
5. a plain statement from the observer:
   - opened
   - did not open
   - opened wrong point

## Stop conditions

Stop the live cycle and return to analysis if:

- a wrong physical point opens
- `PortLog` starts showing new controller-side faults after the probe
- more than 3 payload hypotheses fail for the same point
- `TcpLog` stops changing entirely while the backend still reports send success
