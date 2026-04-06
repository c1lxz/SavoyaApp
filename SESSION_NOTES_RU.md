# Сводка по диагностике `config.mdb`

Дата: 2026-04-06

## Что уже сделали

1. Проверили запуск скриптов из `cmd`.
2. Убедились, что проблема была не в команде запуска, а в открытии базы через ODBC.
3. Проверили `64-bit Python`:
   - `py -3.12 -c "import struct; print(struct.calcsize('P')*8)"` -> `64`
4. Проверили `64-bit` драйверы:
   - `py -3.12 -c "import pyodbc; print(pyodbc.drivers())"`
   - драйвер `Microsoft Access Driver (*.mdb, *.accdb)` был виден
5. При открытии `config.mdb` через современный Access ODBC driver получали ошибку:
   - `Cannot open a database created with a previous version of your application. (-1019)`
6. Обнаружили lock-файл:
   - `C:\GATE\Server\config.ldb`
7. Обновили скрипты:
   - [scripts/check_gate_mdb.ps1](/e:/savoya/SavoyaApp/scripts/check_gate_mdb.ps1)
   - [scripts/find_gate_key.ps1](/e:/savoya/SavoyaApp/scripts/find_gate_key.ps1)
   - теперь они сначала создают временную копию `config.mdb`, а потом читают уже её

## Что выяснили дальше

1. Поставили `32-bit Python`.
2. Сначала `32-bit Python` не видел Access driver.
3. Потом удалили старый `64-bit` Access driver и поставили `32-bit` Access/Jet driver.
4. В `C:\Windows\SysWOW64\odbcad32.exe` появился старый драйвер:
   - `Driver do Microsoft Access (*.mdb)`
5. Через этот старый драйвер подключение продвинулось дальше, но не открылось без security-файла.

## Ключевая находка

В папке `C:\GATE\Server` найден файл:

- `Gate.mdw`

Команда:

```bat
dir "C:\GATE\Server\*.mdw"
```

Результат:

- `C:\GATE\Server\Gate.mdw`

Это означает, что `config.mdb` защищена через старую `Jet/Access workgroup security`.

## Что уже проверили по подключению

Подключение через старый Jet-драйвер без `SystemDB` давало ошибку прав:

```bat
py -3.12-32 -c "import pyodbc; conn=pyodbc.connect(r'DRIVER={Driver do Microsoft Access (*.mdb)};DBQ=%MDB%'); print('OK')"
```

Подключение с `SystemDB` дошло до проверки учётных данных:

```bat
py -3.12-32 -c "import pyodbc; conn=pyodbc.connect(r'DRIVER={Driver do Microsoft Access (*.mdb)};DBQ=C:\GATE\Server\config.mdb;SystemDB=C:\GATE\Server\Gate.mdw'); print('OK')"
```

и

```bat
py -3.12-32 -c "import pyodbc; conn=pyodbc.connect(r'DRIVER={Driver do Microsoft Access (*.mdb)};DBQ=C:\GATE\Server\config.mdb;SystemDB=C:\GATE\Server\Gate.mdw;UID=Admin;PWD='); print('OK')"
```

Обе команды дали ошибку:

- `Недопустимое имя учетной записи или пароль. (-1902)`

## Текущий точный вывод

Проблема уже не в:
- команде запуска
- PowerShell
- `cmd`
- копировании `config.mdb`
- разрядности Python

Текущая реальная проблема:

- для открытия `C:\GATE\Server\config.mdb` нужны правильные `UID` и, возможно, `PWD`
- база использует `Gate.mdw`
- без правильных учётных данных ODBC-подключение не откроется

## Следующий шаг на завтра

Нужно найти, под каким логином и паролем сам Gate открывает `config.mdb`.

Искать:
- в настройках Gate
- в конфигурационных файлах рядом с `C:\GATE`
- у тех, кто устанавливал Gate

Что искать в файлах:
- `UID`
- `PWD`
- `User`
- `Password`
- `SystemDB`
- `Gate.mdw`
- `config.mdb`

Полезные команды для поиска:

```bat
dir /s /b "C:\GATE\*.ini" "C:\GATE\*.cfg" "C:\GATE\*.txt" "C:\GATE\*.xml"
```

```bat
powershell -Command "Get-ChildItem C:\GATE -Recurse -Include *.ini,*.cfg,*.txt,*.xml | Select-String -Pattern 'UID|PWD|Password|User|Gate.mdw|config.mdb|SystemDB'"
```

## Команда, которую нужно будет повторить после нахождения логина/пароля

```bat
py -3.12-32 -c "import pyodbc; conn=pyodbc.connect(r'DRIVER={Driver do Microsoft Access (*.mdb)};DBQ=C:\GATE\Server\config.mdb;SystemDB=C:\GATE\Server\Gate.mdw;UID=ВАШ_ЛОГИН;PWD=ВАШ_ПАРОЛЬ'); print('OK')"
```

Если увидим `OK`, дальше нужно будет:

1. обновить `scripts/check_gate_mdb.ps1`
2. обновить `scripts/find_gate_key.ps1`
3. зашить туда:
   - `py -3.12-32`
   - `Driver do Microsoft Access (*.mdb)`
   - `SystemDB=C:\GATE\Server\Gate.mdw`
   - `UID/PWD`

## Важные файлы проекта

- [README.md](/e:/savoya/SavoyaApp/README.md)
- [scripts/check_gate_mdb.ps1](/e:/savoya/SavoyaApp/scripts/check_gate_mdb.ps1)
- [scripts/find_gate_key.ps1](/e:/savoya/SavoyaApp/scripts/find_gate_key.ps1)
- [SESSION_NOTES_RU.md](/e:/savoya/SavoyaApp/SESSION_NOTES_RU.md)
