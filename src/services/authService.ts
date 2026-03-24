import { AuthResult, User } from '@/types';

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
    // TODO: replace mock login with POST /auth/login
    // TODO: store JWT token
    // TODO: handle refresh token
    await sleep(500, 1000);

    if (login === 'demo' && password === 'demo123') {
      currentUser = DEMO_USER;
      return { success: true, user: DEMO_USER };
    }

    return { success: false, error: 'Неверный логин или пароль' };
  },
  async logout() {
    currentUser = null;
  },
  async getCurrentUser() {
    return currentUser;
  },
};

