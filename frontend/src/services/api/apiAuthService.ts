import { AuthResult, User } from '@/types';
import { apiRequest } from '@/services/api/httpClient';
import { getAccessToken, restoreAccessToken, setAccessToken } from '@/services/api/tokenStore';

type CompatLoginResponse = {
  success: boolean;
  user?: User;
  error?: string;
  access_token?: string;
  requiresProfileCompletion?: boolean;
};

type BackendUser = {
  id: number;
  phone: string;
  name?: string | null;
  apartment?: string | null;
  is_admin?: boolean;
};

type BackendTokenResponse = {
  access_token: string;
  token_type: string;
  user: BackendUser;
};

let currentUser: User | null = null;

const mapBackendUser = (user: BackendUser): User => ({
  id: String(user.id),
  login: user.phone,
  fullName: user.name ?? '',
  plotNumber: user.apartment ?? '',
});

export const apiAuthService = {
  async login(login: string, password: string): Promise<AuthResult> {
    const result = await apiRequest<CompatLoginResponse | BackendTokenResponse>('/auth/login', {
      method: 'POST',
      body: { login, password },
    });

    if ('token_type' in result && 'access_token' in result) {
      const mappedUser = mapBackendUser(result.user);
      await setAccessToken(result.access_token);
      currentUser = mappedUser;
      return {
        success: true,
        user: mappedUser,
        requiresProfileCompletion: !Boolean(mappedUser.fullName.trim()),
      };
    }

    if (result.success && result.access_token && result.user) {
      await setAccessToken(result.access_token);
      currentUser = result.user;
    }

    return {
      success: result.success,
      user: result.user,
      error: result.error,
      requiresProfileCompletion: result.requiresProfileCompletion,
    };
  },
  async logout(): Promise<void> {
    await setAccessToken(null);
    currentUser = null;
  },
  async getCurrentUser(): Promise<User | null> {
    if (currentUser) {
      return currentUser;
    }

    await restoreAccessToken();
    if (!getAccessToken()) {
      return null;
    }

    try {
      const actual = await apiRequest<User>('/user/me');
      currentUser = actual;
      return actual;
    } catch {
      await setAccessToken(null);
      currentUser = null;
      return null;
    }
  },
  async updateProfile(fullName: string, plotNumber?: string): Promise<User> {
    const updated = await apiRequest<User>('/user/profile', {
      method: 'PUT',
      body: { fullName, plotNumber },
    });
    currentUser = updated;
    return updated;
  },
};
