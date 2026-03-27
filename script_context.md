1. Цель
Написать Python-скрипт (gate_db.py), который:

Подключается к базе данных Gate (файл .mdb)

Добавляет временные ключи доступа для гостей (номера телефонов и госномера)

Добавляет постоянные ключи для жителей

Удаляет ключи по истечении времени

Решает проблему с повторяющимися номерами (один и тот же госномер не может быть добавлен дважды)

Скрипт будет использоваться FastAPI-бэкендом.

2. Два типа пропусков
В приложении будет два типа пропусков:

Тип	Кому	Срок	Действие
Временный	Гости, курьеры	На несколько часов (3, 5, 12)	Автоматически удаляется
Постоянный	Жители	Бессрочно (10 лет)	Не удаляется
Скрипт должен уметь работать с обоими типами.

3. Проблема с курьерами (почему это важно)
Суть проблемы
В Gate один и тот же госномер (или номер телефона) не может быть добавлен в базу дважды. Это техническое ограничение: в таблице Keys нет дубликатов по полю key_value для одного типа ключа.

Как это выглядит на практике:

Житель А создаёт заявку для курьера с номером А123ВВ

Скрипт добавляет госномер А123ВВ в таблицу Keys

Курьер приезжает → камера считывает номер → Gate открывает

Житель Б хочет пригласить этого же курьера в этот же день

Скрипт пытается добавить А123ВВ → ошибка или игнор, потому что номер уже есть

Житель Б не может создать заявку

Почему это проблема
Номер остаётся в базе до истечения времени (например, до конца дня)

Второй житель не может "переиспользовать" этот номер

Курьер, который уже был, не может приехать к другому жителю

4. Решение: проверка существования + продление времени
Скрипт должен не просто добавлять номер, а проверять, существует ли он уже.

Если номер уже есть в базе, нужно:

Продлить срок действия (установить новую дату valid_to)

Не создавать дубликат

Важно: Постоянные пропуска (для жителей) создаются один раз и не удаляются. Для них не нужно продление — если номер уже есть, скрипт просто возвращает существующий key_id.

5. Структура базы данных (ключевые таблицы)
5.1. Users — пользователи
Поле	Тип	Описание
id	AutoNumber	Уникальный ID
last_name	Text	Фамилия
first_name	Text	Имя
is_visitor	Boolean	Гость (1) / житель (0)
created_at	Date/Time	Дата создания
5.2. Keys — ключи/идентификаторы доступа
Поле	Тип	Описание
id	AutoNumber	Уникальный ID
user_id	Number	Связь с пользователем
key_type	Text	Тип: Phone, VehicleNumber
key_value	Text	Значение (номер телефона, госномер)
is_blocked	Boolean	Заблокирован (1) / активен (0)
valid_from	Date/Time	Начало действия
valid_to	Date/Time	Окончание действия (NULL для постоянных)
5.3. AccessPoints — точки доступа
Поле	Тип	Описание
id	AutoNumber	ID точки
name	Text	Название (Въезд, Калитка 1)
5.4. AccessPermissions — права доступа
Поле	Тип	Описание
id	AutoNumber	ID
user_id	Number	ID пользователя
access_point_id	Number	ID точки доступа
is_permanent	Boolean	Постоянный доступ (1)
6. Функции скрипта
Функция	Что делает	Возвращает
add_permanent_key(key_type, key_value, access_point_ids, resident_name)	Добавляет постоянный ключ для жителя. Если номер уже есть — возвращает существующий key_id	key_id
add_temporary_key(key_type, key_value, expires_at, access_point_ids)	Добавляет временный ключ для гостя. Если номер уже есть — продлевает срок	key_id
remove_key(key_id)	Удаляет временный ключ (постоянные не удаляет)	bool
get_access_points()	Возвращает список точек доступа	list
7. Пример реализации
python
# gate_db.py
import pyodbc
import os
from datetime import datetime
from typing import List, Optional

MDB_PATH = os.getenv("GATE_MDB_PATH", r"C:\Program Files\Gate\Data\config.mdb")

def get_connection():
    conn_str = f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={MDB_PATH}"
    return pyodbc.connect(conn_str)


def _create_user(name: str, is_visitor: bool) -> int:
    """Создаёт пользователя и возвращает его ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO Users (last_name, first_name, is_visitor, created_at)
        VALUES (?, ?, ?, ?)
    """, (name, name, 1 if is_visitor else 0, datetime.now()))
    
    conn.commit()
    user_id = cursor.execute("SELECT @@IDENTITY").fetchval()
    conn.close()
    return user_id


def _create_key(user_id: int, key_type: str, key_value: str, valid_from: datetime, valid_to: Optional[datetime]) -> int:
    """Создаёт ключ и возвращает его ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO Keys (user_id, key_type, key_value, valid_from, valid_to, is_blocked)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (user_id, key_type, key_value, valid_from, valid_to))
    
    conn.commit()
    key_id = cursor.execute("SELECT @@IDENTITY").fetchval()
    conn.close()
    return key_id


def _add_access_permissions(user_id: int, access_point_ids: List[int], is_permanent: bool) -> None:
    """Добавляет права доступа для пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    for ap_id in access_point_ids:
        # Проверяем, нет ли уже такого права
        cursor.execute("""
            SELECT id FROM AccessPermissions 
            WHERE user_id = ? AND access_point_id = ?
        """, (user_id, ap_id))
        
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO AccessPermissions (user_id, access_point_id, is_permanent)
                VALUES (?, ?, ?)
            """, (user_id, ap_id, 1 if is_permanent else 0))
    
    conn.commit()
    conn.close()


def add_permanent_key(
    key_type: str,           # "Phone" или "VehicleNumber"
    key_value: str,          # номер телефона или госномер
    access_point_ids: List[int],
    resident_name: str = "Житель"
) -> int:
    """
    Добавляет постоянный ключ для жителя.
    Если номер уже существует, возвращает существующий key_id.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Проверяем, есть ли уже такой ключ
    cursor.execute("""
        SELECT id, user_id FROM Keys 
        WHERE key_type = ? AND key_value = ? AND is_blocked = 0
    """, (key_type, key_value))
    
    existing = cursor.fetchone()
    
    if existing:
        key_id, user_id = existing
        conn.close()
        return key_id
    
    # Создаём нового пользователя
    user_id = _create_user(resident_name, is_visitor=False)
    
    # Создаём ключ (valid_to = NULL означает бессрочно)
    key_id = _create_key(user_id, key_type, key_value, datetime.now(), None)
    
    # Добавляем права доступа (постоянные)
    _add_access_permissions(user_id, access_point_ids, is_permanent=True)
    
    return key_id


def add_temporary_key(
    key_type: str,           # "Phone" или "VehicleNumber"
    key_value: str,          # номер телефона или госномер
    expires_at: datetime,    # срок окончания
    access_point_ids: List[int]
) -> int:
    """
    Добавляет временный ключ для гостя.
    Если номер уже существует, продлевает срок действия.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Проверяем, есть ли уже такой ключ
    cursor.execute("""
        SELECT id, user_id, valid_to FROM Keys 
        WHERE key_type = ? AND key_value = ? AND is_blocked = 0
    """, (key_type, key_value))
    
    existing = cursor.fetchone()
    
    if existing:
        key_id, user_id, current_valid_to = existing
        
        # Продлеваем срок, если новый больше
        if expires_at > current_valid_to:
            cursor.execute("""
                UPDATE Keys SET valid_to = ? WHERE id = ?
            """, (expires_at, key_id))
        
        # Добавляем недостающие права доступа (временные)
        for ap_id in access_point_ids:
            cursor.execute("""
                SELECT id FROM AccessPermissions 
                WHERE user_id = ? AND access_point_id = ?
            """, (user_id, ap_id))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO AccessPermissions (user_id, access_point_id, is_permanent)
                    VALUES (?, ?, 0)
                """, (user_id, ap_id))
        
        conn.commit()
        conn.close()
        return key_id
    
    else:
        # Создаём нового пользователя (гостя)
        user_id = _create_user(key_value, is_visitor=True)
        
        # Создаём временный ключ
        key_id = _create_key(user_id, key_type, key_value, datetime.now(), expires_at)
        
        # Добавляем права доступа (временные)
        _add_access_permissions(user_id, access_point_ids, is_permanent=False)
        
        return key_id


def remove_key(key_id: int) -> bool:
    """
    Удаляет временный ключ и связанные права доступа.
    Постоянные ключи не удаляет.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Проверяем, что ключ временный (valid_to не NULL)
    cursor.execute("SELECT user_id, valid_to FROM Keys WHERE id = ?", (key_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    
    user_id, valid_to = row
    
    # Если ключ постоянный (valid_to IS NULL) — не удаляем
    if valid_to is None:
        conn.close()
        return False
    
    # Удаляем права доступа
    cursor.execute("DELETE FROM AccessPermissions WHERE user_id = ?", (user_id,))
    
    # Удаляем ключ
    cursor.execute("DELETE FROM Keys WHERE id = ?", (key_id,))
    
    # Удаляем пользователя (гостя)
    cursor.execute("DELETE FROM Users WHERE id = ?", (user_id,))
    
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def get_access_points() -> List[dict]:
    """
    Возвращает список точек доступа (шлагбаумы, калитки)
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM AccessPoints ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1]} for row in rows]
8. Конфигурация
python
import os
from dotenv import load_dotenv

load_dotenv()

MDB_PATH = os.getenv("GATE_MDB_PATH", r"C:\Program Files\Gate\Data\config.mdb")
Файл .env:

text
GATE_MDB_PATH=C:\test\config.mdb
9. Установка зависимостей
bash
pip install pyodbc python-dotenv
Драйвер: Microsoft Access Database Engine (скачать бесплатно)

10. Важные замечания
Момент	Как решается
Госномер в скрипте	key_type = 'VehicleNumber'
Номер телефона в скрипте	key_type = 'Phone'
Постоянный пропуск (житель)	add_permanent_key() — valid_to = None
Временный пропуск (гость)	add_temporary_key() — valid_to задаётся
Один номер — несколько заявок	Продлеваем valid_to у существующего ключа
Повторяющийся госномер	Проверка существования → продление, а не дубль