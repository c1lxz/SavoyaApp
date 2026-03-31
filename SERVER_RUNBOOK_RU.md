# SavoyaApp: запуск и проверка на реальном сервере Gate

Документ для сценария: backend запускается на том же ПК, где установлен Gate Server и лежит `config.mdb`.

## 1. Что должно быть установлено на сервере
- Windows ПК с установленным ПО Gate-Server-Terminal (рабочая система объекта).
- Запущенные компоненты Gate:
  - `Сервер GATE` (обязательно, должен работать постоянно).
  - `GATE-Terminal` (для проверки событий и конфигурации).
  - `Gate Commander`/`GATE-VIZIT-Commander` (если используется на объекте для домофонной части).
- Python 3.12.
- Python-пакеты проекта (`backend/requirements.txt`).
- ODBC драйвер Access: `Microsoft Access Driver (*.mdb, *.accdb)`.

## 2. Подготовка проекта на сервере
1. Скопируйте папку проекта на сервер, например: `E:\savoya\SavoyaApp`.
2. Откройте PowerShell от имени администратора.
3. Перейдите в папку проекта:
   - `cd E:\savoya\SavoyaApp`
4. Установите зависимости:
   - `py -3.12 -m pip install -r backend/requirements.txt`

## 3. Настройка `.env`
Пример рабочего `.env` для реального сервера:

```env
DATABASE_URL=sqlite+aiosqlite:///./backend_prod.db
DEBUG=False
GATE_REAL_INTEGRATION_ENABLED=True
GATE_MDB_PATH=C:/Gate/Server/config.mdb
GATE_WIEGAND_TRANSPORT=dry_run
GATE_WIEGAND_TIMEOUT_SECONDS=2.0
COURIER_TTL_ONLY_ENABLED=True
COURIER_DEFAULT_HOURS=2
COURIER_MAX_HOURS=12
```

Пояснения:
- `GATE_MDB_PATH` должен указывать на реальный `config.mdb` сервера Gate.
- Bridge-переменные (`GATE_BRIDGE_*`) больше не используются.
- На первом этапе держите `GATE_WIEGAND_TRANSPORT=dry_run`, чтобы проверить бизнес-цепочку без физического открытия.

## 4. Проверка, что Gate-система в норме (до запуска backend)
1. Запустите `Сервер GATE` и убедитесь, что он без ошибок.
2. Проверьте логи сервера Gate:
   - `C:\Gate\Server\ErrLog\`
   - при необходимости: `C:\Gate\Server\DebugLog\`
3. В `GATE-Terminal` проверьте вход оператора и доступ к текущей конфигурации.
4. Если в системе используются удаленные серверы/домофоны, проверьте их штатный статус в Gate-интерфейсах (Terminal/Commander).

## 5. Запуск backend
Из папки проекта:

```powershell
py -3.12 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Проверка:
- Откройте в браузере `http://127.0.0.1:8000/health`.
- Ожидаемый ответ: `{"status":"ok"}`.

## 6. Тестовый прогон API на сервере
### 6.1 Авторизация
`POST /api/auth/login`

### 6.2 Создание заявки/пропуска
`POST /api/requests/`

### 6.3 Команда открытия
`POST /api/access/open`

Если `GATE_WIEGAND_TRANSPORT=dry_run`, API должен вернуть успешный технический ответ без физического срабатывания точки прохода.

## 7. Что смотреть в Gate-программах во время теста
- `GATE-Terminal`:
  - события прохода/команд;
  - актуальность точек доступа и прав;
  - корректность операторского входа.
- `Сервер GATE`:
  - отсутствие новых ошибок в `ErrLog`;
  - стабильная работа службы/процесса.
- `Gate Commander` (если используется на объекте):
  - штатная связь с домофонным оборудованием;
  - отсутствие конфликтов после записи ключей/команд из backend.

## 8. Быстрая техническая диагностика из проекта
Проверка доступа к `config.mdb` через Python:

```powershell
@' 
import gate_db
print("Access points:", gate_db.get_access_points())
'@ | py -3.12 -
```

Если команда не выполняется:
- проверьте путь `GATE_MDB_PATH`;
- проверьте ODBC драйвер Access;
- проверьте права Windows на файл `config.mdb`.

## 9. Переход с dry-run на реальное открытие
Переключать только после успешного сухого прогона и проверки с инженером на объекте:
- в `.env` сменить `GATE_WIEGAND_TRANSPORT` на нужный режим интеграции (`http`),
- заполнить `GATE_WIEGAND_HTTP_URL` и (при необходимости) `GATE_WIEGAND_HTTP_TOKEN`,
- повторить тесты из разделов 6-7.

## 10. Важно по архитектуре
Схема соответствует логике руководства Gate Server-Terminal: сервер и терминал работают с основной `config.mdb` напрямую на серверном ПК/в локальной сети. Отдельный bridge-слой для VPS в проекте удален.
