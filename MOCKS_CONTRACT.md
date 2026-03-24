# Контракт заглушек (Mock API Contract)

## 1. Назначение
Данный документ описывает интерфейсы и поведение mock-сервисов. **Экраны должны работать исключительно через эти интерфейсы.** Это гарантирует, что при замене моков на реальный API логика экранов не изменится.

---

## 2. AuthService

### Интерфейс
```typescript
interface AuthService {
  login(login: string, password: string): Promise<AuthResult>;
  logout(): Promise<void>;
  getCurrentUser(): Promise<User | null>;
}
Типы
typescript
type User = {
  id: string;
  login: string;
  fullName: string;
  plotNumber: string;
};

type AuthResult = {
  success: boolean;
  user?: User;
  error?: string;
};
Mock-поведение
Задержка: 500–1000 мс.

Успех: только для пары login: "demo", password: "demo123".

Ошибка: для всех остальных комбинаций.

TODO для замены
typescript
// TODO: replace mock login with POST /auth/login
// TODO: store JWT token
// TODO: handle refresh token
3. PassService
Интерфейс
typescript
interface PassService {
  createPass(payload: CreatePassPayload): Promise<PassItem>;
  getMyPasses(): Promise<PassItem[]>;
  cancelPass(id: string): Promise<void>;
}
Типы
typescript
type CreatePassPayload = {
  carNumber: string;
  plotNumber: string;
  expiresAt: string | null; // ISO строка
  isPermanent: boolean;
};

type PassItem = {
  id: string;
  carNumber: string;
  plotNumber: string;
  expiresAt: string | null; // ISO строка
  isPermanent: boolean;
  status: 'active' | 'expired' | 'permanent';
  createdAt: string; // ISO строка
};
Mock-поведение
Данные хранятся in-memory.

createPass: генерирует id, добавляет в массив.

getMyPasses: возвращает массив.

cancelPass: удаляет элемент.

Логика статусов:

Если isPermanent === true: status = "permanent".

Если expiresAt < Date.now(): status = "expired".

Иначе: status = "active".

TODO для замены
typescript
// TODO: POST /passes
// TODO: GET /passes/my
// TODO: DELETE /passes/{id}
// TODO: backend должен считать статус, не frontend
4. GateService
Интерфейс
typescript
interface GateService {
  openBarrier(type: 'entry' | 'exit'): Promise<GateActionResult>;
}
Типы
typescript
type GateActionResult = {
  success: boolean;
  action: 'entry' | 'exit';
  message: string;
  timestamp: string; // ISO строка
};
Mock-поведение
Задержка: 500–1200 мс.

Успех в 90% случаев, ошибка в 10% (для демонстрации).

TODO для замены
typescript
// TODO: POST /gates/open
// TODO: передавать gate_id
// TODO: обрабатывать реальные ошибки (timeout, denied, etc)
5. Контракт состояния (UI States)
Состояния запроса
typescript
type RequestState = 'idle' | 'loading' | 'success' | 'error';
Глобальное состояние (пример)
typescript
type AppState = {
  user: User | null;
  passes: PassItem[];
  isLoading: boolean;
  error: string | null;
};
TODO для замены
typescript
// TODO: синхронизация с backend
// TODO: кэширование данных
// TODO: обработка offline режима
6. Контракт ошибок
Тип ошибки
typescript
type AppError = {
  message: string;
  code?: string;
};
Примеры сообщений
"Неверный логин или пароль"

"Не удалось открыть шлагбаум"

"Ошибка сети"

TODO для замены
typescript
// TODO: заменить на реальные ошибки API
// TODO: маппинг кодов ошибок backend -> UI
7. Контракт дат
Формат: ISO 8601 (YYYY-MM-DDTHH:mm:ssZ).

Отображение на клиенте: форматировать локально (например, DD.MM.YYYY).

Постоянный пропуск: отображать как "Постоянный" или "Без срока".

TODO для замены
typescript
// TODO: backend должен возвращать даты
// TODO: учитывать timezone
8. Критерий готовности архитектуры
Архитектура готова к замене моков на API, если:

Ни один экран не содержит прямой работы с localStorage, setTimeout моками или хардкодом данных.

Все данные поступают через сервисы (authService, passService, gateService).

Типы данных (User, PassItem) используются строго.

Замена файла реализации сервиса (например, mockAuthService на apiAuthService) не требует изменений в коде экранов.