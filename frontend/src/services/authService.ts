import { AuthResult, User } from '@/types';
import { apiAuthService } from '@/services/api/apiAuthService';
import { USE_REAL_API } from '@/services/api/config';

export interface AuthService {
  login(login: string, password: string): Promise<AuthResult>;
  logout(): Promise<void>;
  getCurrentUser(): Promise<User | null>;
}

const DEMO_USER: User = {
  id: '1',
  login: 'demo',
  fullName: 'Демо Пользователь',
  plotNumber: '25',
};

let currentUser: User | null = null;

const sleep = (minMs: number, maxMs: number) =>
  new Promise<void>((resolve) => {
    const timeout = Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
    setTimeout(resolve, timeout);
  });

export const mockAuthService: AuthService = {
  async login(login: string, password: string) {
    if (USE_REAL_API) {
      return apiAuthService.login(login, password);
    }

    await sleep(500, 1000);

    if (login === 'demo' && password === 'demo123') {
      currentUser = DEMO_USER;
      return { success: true, user: DEMO_USER };
    }

    return { success: false, error: 'Неверный логин или пароль' };
  },
  async logout() {
    if (USE_REAL_API) {
      await apiAuthService.logout();
      return;
    }
    currentUser = null;
  },
  async getCurrentUser() {
    if (USE_REAL_API) {
      return apiAuthService.getCurrentUser();
    }
    return currentUser;
  },
};
