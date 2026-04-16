import { Platform } from 'react-native';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
const IS_WEB = Platform.OS === 'web';

const isLoopbackHost = (hostname: string): boolean => LOOPBACK_HOSTS.has(hostname.toLowerCase());

const getWebOrigin = (): string | null => {
  if (!IS_WEB || typeof window === 'undefined') {
    return null;
  }

  return window.location?.origin ?? null;
};

const resolveDefaultApiBaseUrl = (): string => {
  const webOrigin = getWebOrigin();
  if (webOrigin) {
    return `${webOrigin}/api`;
  }

  return 'http://localhost:8000/api';
};

const resolveApiBaseUrl = (): string => {
  const configured = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (!configured) {
    return resolveDefaultApiBaseUrl();
  }

  const webOrigin = getWebOrigin();
  if (!webOrigin) {
    return configured;
  }

  try {
    const currentUrl = new URL(webOrigin);
    const targetUrl = new URL(configured, webOrigin);

    // If the bundle was built with localhost API settings and is now running
    // on a real domain, switch back to same-origin requests automatically.
    if (!isLoopbackHost(currentUrl.hostname) && isLoopbackHost(targetUrl.hostname)) {
      return `${webOrigin}/api`;
    }

    // Local web builds also should prefer same-origin /api when the current
    // page is already behind a frontend proxy on another port.
    if (
      isLoopbackHost(currentUrl.hostname) &&
      isLoopbackHost(targetUrl.hostname) &&
      currentUrl.origin !== targetUrl.origin
    ) {
      return `${webOrigin}/api`;
    }
  } catch {
    // Leave invalid custom values untouched so request errors stay explicit.
  }

  return configured;
};

const normalizeApiBaseUrl = (value: string): string => {
  const trimmed = value.trim().replace(/\/+$/, '');
  if (trimmed.endsWith('/api')) {
    return trimmed.slice(0, -4);
  }
  return trimmed;
};

const resolveUseRealApi = (): boolean => {
  const configured = process.env.EXPO_PUBLIC_USE_REAL_API?.trim().toLowerCase();
  if (configured === 'true') {
    return true;
  }
  if (configured === 'false') {
    return false;
  }

  // Default to the backend API. Mock mode still can be forced explicitly.
  return true;
};

export const API_BASE_URL = normalizeApiBaseUrl(resolveApiBaseUrl());
export const USE_REAL_API = resolveUseRealApi();
