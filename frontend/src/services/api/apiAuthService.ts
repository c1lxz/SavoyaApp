import { AuthResult, User } from '@/types';
import { apiRequest } from '@/services/api/httpClient';
import { setAccessToken } from '@/services/api/tokenStore';

type LoginResponse = {
  success: boolean;
  user?: User;
  error?: string;
  access_token?: string;
};

let currentUser: User | null = null;

export const apiAuthService = {
  async login(login: string, password: string): Promise<AuthResult> {
    const result = await apiRequest<LoginResponse>('/auth/login', {
      method: 'POST',
      body: { login, password },
    });

    if (result.success && result.access_token && result.user) {
      setAccessToken(result.access_token);
      currentUser = result.user;
    }

    return {
      success: result.success,
      user: result.user,
      error: result.error,
    };
  },
  async logout(): Promise<void> {
    setAccessToken(null);
    currentUser = null;
  },
  async getCurrentUser(): Promise<User | null> {
    return currentUser;
  },
};
