1. Цель
Написать бэкенд на FastAPI, который:

Принимает запросы от фронтенда (React Native)

Использует готовый скрипт gate_db.py для работы с Gate

Управляет созданием и отменой заявок

Обрабатывает открытие шлагбаумов и калиток

Хранит данные о заявках, пользователях и логах в PostgreSQL

2. Технологии
Компонент	Технология
Фреймворк	FastAPI (последняя версия)
База данных	PostgreSQL (через asyncpg или SQLAlchemy)
Аутентификация	JWT (токен в Authorization: Bearer)
SMS-код для входа	smsc.ru API
Логирование	Python logging
Конфигурация	Pydantic Settings
3. Структура проекта
text
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI приложение
│   ├── config.py               # Настройки (Pydantic Settings)
│   ├── database.py             # Подключение к PostgreSQL
│   ├── models.py               # SQLAlchemy модели
│   ├── schemas.py              # Pydantic схемы
│   ├── dependencies.py         # Зависимости (get_current_user)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py             # Регистрация, вход, SMS-код
│   │   ├── gate.py             # Открытие шлагбаумов/калиток
│   │   ├── requests.py         # Создание/отмена заявок
│   │   └── user.py             # Профиль, мои пропуски, история
│   ├── services/
│   │   ├── __init__.py
│   │   ├── sms.py              # Отправка SMS через smsc.ru
│   │   ├── gate.py             # Обёртка над gate_db.py
│   │   └── cleanup.py          # Автоудаление истекших заявок
│   └── utils/
│       └── jwt.py              # Генерация и проверка JWT
├── .env                        # Переменные окружения
├── requirements.txt
└── docker-compose.yml          # Для локальной разработки
4. Переменные окружения (.env)
env
# База данных
DATABASE_URL=postgresql://user:password@localhost:5432/gate_app

# JWT
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=43200  # 30 дней

# SMSC.ru
SMSC_LOGIN=your_login
SMSC_PASSWORD=your_password
SMSC_API_KEY=your_api_key

# Gate .mdb
GATE_MDB_PATH=C:\Program Files\Gate\Data\config.mdb

# Приложение
APP_NAME=GateApp
DEBUG=True
5. Модели базы данных (PostgreSQL)
5.1. Users — пользователи приложения (жители)
sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100),
    apartment VARCHAR(20),
    is_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    gate_user_id INTEGER,           -- ID пользователя в Gate (из .mdb)
    created_at TIMESTAMP DEFAULT NOW()
);
5.2. Requests — заявки на пропуск
sql
CREATE TABLE requests (
    id SERIAL PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_type VARCHAR(20) NOT NULL,      -- 'Phone' или 'VehicleNumber'
    key_value VARCHAR(50) NOT NULL,     -- номер телефона или госномер
    gate_key_id INTEGER,                -- ID ключа в Gate (из .mdb)
    access_point_ids JSONB,              -- список ID точек доступа
    is_permanent BOOLEAN DEFAULT FALSE, -- постоянный пропуск для жителей
    expires_at TIMESTAMP,               -- NULL для постоянных
    status VARCHAR(20) DEFAULT 'active', -- active, expired, cancelled
    created_at TIMESTAMP DEFAULT NOW(),
    cancelled_at TIMESTAMP
);
5.3. Logs — журнал открытий
sql
CREATE TABLE logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action VARCHAR(50) NOT NULL,        -- 'open_gate', 'open_gateway'
    access_point_id INTEGER,             -- ID точки доступа в Gate
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
5.4. SmsCodes — коды для входа
sql
CREATE TABLE sms_codes (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) NOT NULL,
    code VARCHAR(6) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    is_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
6. Pydantic схемы (schemas.py)
6.1. Auth
python
class SmsRequest(BaseModel):
    phone: str

class SmsVerifyRequest(BaseModel):
    phone: str
    code: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
6.2. User
python
class UserResponse(BaseModel):
    id: int
    phone: str
    name: Optional[str]
    apartment: Optional[str]
    is_admin: bool
6.3. Gate
python
class OpenGateRequest(BaseModel):
    access_point_id: int   # ID точки доступа (шлагбаум, калитка)

class OpenGateResponse(BaseModel):
    success: bool
    message: str
6.4. Requests
python
class CreateRequestRequest(BaseModel):
    key_type: str           # "Phone" или "VehicleNumber"
    key_value: str
    access_point_ids: List[int]
    is_permanent: bool = False
    hours: Optional[int] = None   # для временных пропусков

class RequestResponse(BaseModel):
    id: int
    resident_id: int
    key_type: str
    key_value: str
    is_permanent: bool
    expires_at: Optional[datetime]
    status: str
    created_at: datetime
6.5. Access Points
python
class AccessPointResponse(BaseModel):
    id: int
    name: str
7. Эндпоинты (routers)
7.1. Auth (/api/auth)
Метод	Эндпоинт	Описание
POST	/send-sms	Отправляет SMS-код на номер
POST	/verify	Проверяет код, возвращает JWT
POST	/logout	Завершает сессию (удаляет токен на клиенте)
7.2. Gate (/api/gate)
Метод	Эндпоинт	Описание
GET	/access-points	Возвращает список точек доступа (шлагбаумы, калитки)
POST	/open	Открывает указанную точку доступа
7.3. Requests (/api/requests)
Метод	Эндпоинт	Описание
POST	/	Создаёт заявку (временный или постоянный пропуск)
GET	/	Возвращает список заявок текущего пользователя
DELETE	/{request_id}	Отменяет заявку (удаляет ключ из Gate, если нет других заявок)
7.4. User (/api/user)
Метод	Эндпоинт	Описание
GET	/me	Возвращает данные текущего пользователя
GET	/logs	Возвращает историю открытий пользователя
8. Логика работы (основные сценарии)
8.1. Вход в приложение
Пользователь вводит номер телефона → /auth/send-sms

Бэкенд генерирует 4-значный код, сохраняет в sms_codes, отправляет через smsc.ru

Пользователь вводит код → /auth/verify

Бэкенд проверяет код, создаёт/находит пользователя в users, возвращает JWT

8.2. Создание временного пропуска (гость)
Житель вызывает /requests с key_type, key_value, hours, access_point_ids

Бэкенд:

Создаёт запись в requests со статусом active

Вызывает gate_db.add_temporary_key()

Сохраняет gate_key_id в запись

Возвращает данные заявки

8.3. Создание постоянного пропуска (житель)
Житель вызывает /requests с is_permanent=True

Бэкенд:

Создаёт запись в requests (expires_at = NULL)

Вызывает gate_db.add_permanent_key()

Возвращает данные заявки

8.4. Отмена пропуска
Житель вызывает DELETE /requests/{id}

Бэкенд:

Проверяет, что заявка принадлежит пользователю

Обновляет статус на cancelled

Если это временная заявка и других активных заявок на этот key_value нет:

Вызывает gate_db.remove_key(gate_key_id)

8.5. Открытие шлагбаума/калитки
Житель вызывает /gate/open с access_point_id

Бэкенд:

Проверяет, что пользователь имеет доступ (есть постоянный пропуск или активная заявка)

Логирует действие в logs

Возвращает success: true

(Здесь логика открытия зависит от того, как Gate открывается — через .mdb, API или Wiegand)

9. Сервис автоудаления (cleanup.py)
Запускается по cron (раз в минуту) или через BackgroundTasks:

python
async def cleanup_expired_requests():
    """Удаляет истекшие заявки и соответствующие ключи из Gate"""
    expired = db.query(Requests).filter(
        Requests.status == "active",
        Requests.expires_at <= datetime.now(),
        Requests.is_permanent == False
    ).all()
    
    for req in expired:
        # Проверяем, есть ли другие активные заявки на этот key_value
        other_active = db.query(Requests).filter(
            Requests.id != req.id,
            Requests.key_value == req.key_value,
            Requests.status == "active"
        ).count()
        
        if other_active == 0:
            # Удаляем ключ из Gate
            gate_db.remove_key(req.gate_key_id)
        
        # Обновляем статус заявки
        req.status = "expired"
    
    db.commit()
10. Зависимости (requirements.txt)
text
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.35
asyncpg==0.29.0
pydantic==2.9.0
pydantic-settings==2.5.0
python-dotenv==1.0.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
httpx==0.27.0
python-multipart==0.0.12
11. Запуск
bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск разработки
uvicorn app.main:app --reload

# Запуск с Docker
docker-compose up -d
12. Mock-контракт (пример запросов/ответов)
Вход
json
POST /api/auth/send-sms
{ "phone": "+79161234567" }
→ { "message": "Код отправлен" }

POST /api/auth/verify
{ "phone": "+79161234567", "code": "1234" }
→ { "access_token": "jwt...", "user": { "id": 1, "phone": "+79161234567", "name": null } }
Создание пропуска
json
POST /api/requests
Authorization: Bearer jwt...
{
    "key_type": "VehicleNumber",
    "key_value": "А123ВВ",
    "access_point_ids": [1, 2],
    "hours": 3
}
→ {
    "id": 101,
    "key_type": "VehicleNumber",
    "key_value": "А123ВВ",
    "is_permanent": false,
    "expires_at": "2025-03-26T18:00:00",
    "status": "active"
}
Открытие шлагбаума
json
POST /api/gate/open
Authorization: Bearer jwt...
{
    "access_point_id": 1
}
→ { "success": true, "message": "Шлагбаум открывается" }
Список точек доступа
json
GET /api/gate/access-points
→ [
    { "id": 1, "name": "Въезд" },
    { "id": 2, "name": "Выезд" },
    { "id": 3, "name": "Калитка 1" },
    { "id": 4, "name": "Калитка 2" }
]
