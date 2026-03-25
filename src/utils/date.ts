const MOSCOW_TIMEZONE = 'Europe/Moscow';

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

export const toIsoDate = (date: Date): string => date.toISOString();
