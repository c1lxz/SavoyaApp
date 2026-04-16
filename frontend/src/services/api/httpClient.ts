import { Platform } from 'react-native';
import { API_BASE_URL } from '@/services/api/config';
import { getAccessToken } from '@/services/api/tokenStore';

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
};

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
const IS_WEB = Platform.OS === 'web';

const isLoopbackHost = (hostname: string): boolean => LOOPBACK_HOSTS.has(hostname.toLowerCase());

const getWebOrigin = (): string | null => {
  if (!IS_WEB || typeof window === 'undefined') {
    return null;
  }

  return window.location?.origin ?? null;
};

const resolveRequestUrl = (path: string): URL => {
  const webOrigin = getWebOrigin();
  if (webOrigin) {
    return new URL(`${API_BASE_URL}${path}`, webOrigin);
  }

  return new URL(`${API_BASE_URL}${path}`);
};

const resolveErrorMessage = (payload: unknown): string | null => {
  if (typeof payload === 'string') {
    return payload;
  }

  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const record = payload as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === 'string') {
    return detail;
  }

  if (detail && typeof detail === 'object') {
    const nestedMessage = resolveErrorMessage(detail);
    if (nestedMessage) {
      return nestedMessage;
    }

    const detailRecord = detail as Record<string, unknown>;
    if (typeof detailRecord.message === 'string') {
      return detailRecord.message;
    }
    if (typeof detailRecord.code === 'string') {
      return detailRecord.code;
    }
  }

  if (typeof record.message === 'string') {
    return record.message;
  }

  if (typeof record.error === 'string') {
    return record.error;
  }

  return null;
};

export const apiRequest = async <T>(path: string, options: RequestOptions = {}): Promise<T> => {
  const token = getAccessToken();
  const requestUrl = resolveRequestUrl(path);

  if (token && requestUrl.protocol !== 'https:' && !isLoopbackHost(requestUrl.hostname)) {
    throw new Error('Небезопасное соединение с API заблокировано');
  }

  const response = await fetch(requestUrl.toString(), {
    method: options.method ?? 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: 'omit',
    cache: 'no-store',
    redirect: 'error',
    referrerPolicy: 'no-referrer',
  });

  if (!response.ok) {
    let message = 'Ошибка сети';
    try {
      const errorPayload = await response.json();
      message = resolveErrorMessage(errorPayload) ?? message;
    } catch {
      // Use default message.
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
};
