import { Platform } from 'react-native';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
const ABSOLUTE_URL_PATTERN = /^[a-z][a-z\d+.-]*:\/\//i;
const DEFAULT_NATIVE_PUBLIC_ORIGIN = 'https://ipksavoya.ru';
const IS_WEB = Platform.OS === 'web';

const isLoopbackHost = (hostname: string): boolean => LOOPBACK_HOSTS.has(hostname.toLowerCase());
const isAbsoluteUrl = (value: string): boolean => ABSOLUTE_URL_PATTERN.test(value);

const getWebOrigin = (): string | null => {
  if (!IS_WEB || typeof window === 'undefined') {
    return null;
  }

  return window.location?.origin ?? null;
};

const normalizeApiBaseUrl = (value: string): string => {
  const trimmed = value.trim().replace(/\/+$/, '');
  if (!trimmed) {
    return '';
  }

  if (!isAbsoluteUrl(trimmed)) {
    return trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  }

  try {
    const parsed = new URL(trimmed);
    const normalizedPath = parsed.pathname.replace(/\/+$/, '');
    return `${parsed.origin}${normalizedPath === '/' ? '' : normalizedPath}`;
  } catch {
    return trimmed;
  }
};

const resolveNativeApiBaseUrl = (configured: string | null): string => {
  if (configured && isAbsoluteUrl(configured)) {
    return normalizeApiBaseUrl(configured);
  }

  const configuredOrigin = process.env.EXPO_PUBLIC_SITE_ORIGIN?.trim();
  if (configuredOrigin) {
    return normalizeApiBaseUrl(configuredOrigin);
  }

  // Native builds cannot resolve relative /api paths without a web origin.
  return DEFAULT_NATIVE_PUBLIC_ORIGIN;
};

const resolveApiBaseUrl = (): string => {
  const configured = process.env.EXPO_PUBLIC_API_BASE_URL?.trim() || '';
  const webOrigin = getWebOrigin();
  if (!webOrigin) {
    return resolveNativeApiBaseUrl(configured || null);
  }

  if (!configured) {
    return webOrigin;
  }

  if (!isAbsoluteUrl(configured) && !configured.startsWith('/')) {
    return normalizeApiBaseUrl(configured);
  }

  try {
    const currentUrl = new URL(webOrigin);
    const targetUrl = isAbsoluteUrl(configured) ? new URL(configured) : new URL(configured, webOrigin);

    // If the bundle was built with localhost API settings and is now running
    // on a real domain, switch back to same-origin requests automatically.
    if (!isLoopbackHost(currentUrl.hostname) && isLoopbackHost(targetUrl.hostname)) {
      return webOrigin;
    }

    // Local web builds also should prefer same-origin /api when the current
    // page is already behind a frontend proxy on another port.
    if (
      isLoopbackHost(currentUrl.hostname) &&
      isLoopbackHost(targetUrl.hostname) &&
      currentUrl.origin !== targetUrl.origin
    ) {
      return webOrigin;
    }

    return targetUrl.origin;
  } catch {
    // Leave invalid custom values untouched so request errors stay explicit.
    return normalizeApiBaseUrl(configured);
  }
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
