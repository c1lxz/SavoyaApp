import { AuthResult, ChangePasswordPayload, User } from '@/types';
import { apiAuthService } from '@/services/api/apiAuthService';
import { USE_REAL_API } from '@/services/api/config';

export interface AuthService {
  login(login: string, password: string): Promise<AuthResult>;
  logout(): Promise<void>;
  getCurrentUser(): Promise<User | null>;
  updateProfile(fullName: string, plotNumber?: string): Promise<User>;
  changePassword(payload: ChangePasswordPayload): Promise<User>;
}

type MockUserRecord = {
  user: User;
  password: string;
  passwordChangePromptShown?: boolean;
};

const MOCK_USERS: MockUserRecord[] = [
  {
    user: {
      id: '1',
      login: 'demo',
      fullName: 'Демо Пользователь',
      plotNumber: '25',
      phoneNumber: '+70000000000',
      isAdmin: false,
      passwordChangeRequired: false,
      passwordChangePromptRequired: false,
    },
    password: 'demo123',
  },
];

let currentUser: User | null = null;

const sleep = (minMs: number, maxMs: number) =>
  new Promise<void>((resolve) => {
    const timeout = Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
    setTimeout(resolve, timeout);
  });

const findMockUser = (login: string) => MOCK_USERS.find((item) => item.user.login === login);

export const mockAuthService: AuthService = {
  async login(login: string, password: string) {
    if (USE_REAL_API) {
      return apiAuthService.login(login, password);
    }

    await sleep(300, 700);

    const record = findMockUser(login);
    if (!record || record.password !== password) {
      return { success: false, error: 'Неверный логин или пароль' };
    }

    const shouldPrompt = Boolean(record.user.passwordChangeRequired && !record.passwordChangePromptShown);
    currentUser = {
      ...record.user,
      passwordChangePromptRequired: shouldPrompt,
    };
    if (shouldPrompt) {
      record.passwordChangePromptShown = true;
    }
    return {
      success: true,
      user: currentUser,
      passwordChangeRequired: Boolean(record.user.passwordChangeRequired),
    };
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

  async updateProfile(fullName: string, plotNumber?: string) {
    if (USE_REAL_API) {
      return apiAuthService.updateProfile(fullName, plotNumber);
    }

    const fallback = MOCK_USERS[0]?.user;
    const next: User = {
      ...(currentUser ?? fallback),
      id: (currentUser ?? fallback)?.id ?? '1',
      login: (currentUser ?? fallback)?.login ?? 'demo',
      fullName: fullName.trim(),
      plotNumber: (plotNumber ?? (currentUser?.plotNumber ?? fallback?.plotNumber ?? '')).trim(),
      phoneNumber: currentUser?.phoneNumber ?? fallback?.phoneNumber ?? '',
      isAdmin: Boolean(currentUser?.isAdmin ?? fallback?.isAdmin),
      passwordChangeRequired: Boolean(currentUser?.passwordChangeRequired ?? fallback?.passwordChangeRequired),
      passwordChangePromptRequired: false,
    };

    currentUser = next;
    const record = findMockUser(next.login);
    if (record) {
      record.user = next;
    }
    return next;
  },

  async changePassword(payload: ChangePasswordPayload) {
    if (USE_REAL_API) {
      return apiAuthService.changePassword(payload);
    }

    await sleep(200, 500);

    if (!currentUser) {
      throw new Error('Пользователь не авторизован');
    }

    const record = findMockUser(currentUser.login);
    if (!record) {
      throw new Error('Пользователь не найден');
    }

    record.password = payload.newPassword;
    record.user = {
      ...record.user,
      passwordChangeRequired: false,
      passwordChangePromptRequired: false,
    };
    currentUser = { ...record.user };
    return currentUser;
  },
};
