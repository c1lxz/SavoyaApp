const MOSCOW_TIMEZONE = 'Europe/Moscow';
const DATE_INPUT_PATTERN = /^(\d{2})\.(\d{2})\.(\d{4})$/;

export const formatDate = (input: string | number | Date): string => {
  const date = new Date(input);
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: MOSCOW_TIMEZONE,
  }).format(date);
};

export const formatDateTime = (input: string | number | Date): string => {
  const date = new Date(input);
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: MOSCOW_TIMEZONE,
  }).format(date);
};

export const addDays = (input: string | number | Date, days: number): Date => {
  const date = new Date(input);
  date.setDate(date.getDate() + days);
  return date;
};

export const endOfDay = (input: string | number | Date): Date => {
  const date = new Date(input);
  date.setHours(23, 59, 59, 999);
  return date;
};

export const formatDateInput = (value: string): string => {
  const digits = value.replace(/\D/g, '').slice(0, 8);

  if (digits.length <= 2) {
    return digits;
  }

  if (digits.length <= 4) {
    return `${digits.slice(0, 2)}.${digits.slice(2)}`;
  }

  return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`;
};

export const parseDateInput = (value: string): Date | null => {
  const match = DATE_INPUT_PATTERN.exec(value.trim());
  if (!match) {
    return null;
  }

  const [, dayValue, monthValue, yearValue] = match;
  const day = Number(dayValue);
  const month = Number(monthValue);
  const year = Number(yearValue);
  const date = new Date(year, month - 1, day);

  if (
    Number.isNaN(date.getTime()) ||
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
};

export const toIsoDate = (date: Date): string => {
  return endOfDay(date).toISOString();
};
