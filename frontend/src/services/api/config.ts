const resolveDefaultApiBaseUrl = (): string => {
  if (typeof window !== 'undefined') {
    return `${window.location.origin}/api`;
  }

  return 'http://localhost:8000/api';
};

const normalizeApiBaseUrl = (value: string): string => {
  const trimmed = value.trim().replace(/\/+$/, '');
  if (trimmed.endsWith('/api')) {
    return trimmed.slice(0, -4);
  }
  return trimmed;
};

export const API_BASE_URL = normalizeApiBaseUrl(process.env.EXPO_PUBLIC_API_BASE_URL ?? resolveDefaultApiBaseUrl());
export const USE_REAL_API = (process.env.EXPO_PUBLIC_USE_REAL_API ?? 'false') === 'true';
