import { AuthResult, ChangePasswordPayload, User } from '@/types';
import { apiRequest } from '@/services/api/httpClient';
import { getAccessToken, restoreAccessToken, setAccessToken } from '@/services/api/tokenStore';

type CompatLoginResponse = {
  success: boolean;
  user?: CompatUserResponse;
  error?: string;
  access_token?: string;
  requiresProfileCompletion?: boolean;
  passwordChangeRequired?: boolean;
  passwordChangePromptRequired?: boolean;
};

type CompatUserResponse = {
  id: string;
  login: string;
  fullName: string;
  plotNumber: string;
  phoneNumber: string;
  isAdmin: boolean;
  passwordChangeRequired?: boolean;
  passwordChangePromptRequired?: boolean;
};

type BackendUser = {
  id: number;
  phone: string;
  name?: string | null;
  apartment?: string | null;
  is_admin?: boolean;
  password_change_required?: boolean;
  password_change_prompt_required?: boolean;
};

type ApiUser = BackendUser | CompatUserResponse;

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
  phoneNumber: user.phone ?? '',
  isAdmin: Boolean(user.is_admin),
  passwordChangeRequired: Boolean(user.password_change_required),
  passwordChangePromptRequired: Boolean(user.password_change_prompt_required),
});

const mapCompatUser = (user: CompatUserResponse): User => ({
  id: String(user.id),
  login: user.login ?? '',
  fullName: user.fullName ?? '',
  plotNumber: user.plotNumber ?? '',
  phoneNumber: user.phoneNumber ?? '',
  isAdmin: Boolean(user.isAdmin),
  passwordChangeRequired: Boolean(user.passwordChangeRequired),
  passwordChangePromptRequired: Boolean(user.passwordChangePromptRequired),
});

const mapApiUser = (user: ApiUser): User => {
  if ('isAdmin' in user) {
    return mapCompatUser(user);
  }

  return mapBackendUser(user);
};

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
        requiresProfileCompletion: !mappedUser.isAdmin && !Boolean(mappedUser.fullName.trim()),
        passwordChangeRequired: Boolean(mappedUser.passwordChangeRequired),
      };
    }

    if (result.success && result.access_token && result.user) {
      const mappedBaseUser = mapApiUser(result.user);
      const mappedUser = {
        ...mappedBaseUser,
        passwordChangePromptRequired: Boolean(
          result.passwordChangePromptRequired ?? mappedBaseUser.passwordChangePromptRequired,
        ),
      };
      await setAccessToken(result.access_token);
      currentUser = mappedUser;
      return {
        success: result.success,
        user: mappedUser,
        error: result.error,
        requiresProfileCompletion: mappedUser.isAdmin ? false : Boolean(result.requiresProfileCompletion),
        passwordChangeRequired: Boolean(result.passwordChangeRequired ?? mappedUser.passwordChangeRequired),
      };
    }

    const mappedFallbackUser = result.user ? mapApiUser(result.user) : undefined;
    return {
      success: result.success,
      user: mappedFallbackUser
        ? {
            ...mappedFallbackUser,
            passwordChangePromptRequired: Boolean(
              result.passwordChangePromptRequired ?? mappedFallbackUser.passwordChangePromptRequired,
            ),
          }
        : undefined,
      error: result.error,
      requiresProfileCompletion: result.user?.isAdmin ? false : result.requiresProfileCompletion,
      passwordChangeRequired: result.passwordChangeRequired,
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
      const actual = await apiRequest<ApiUser>('/user/me');
      const mappedUser = mapApiUser(actual);
      currentUser = mappedUser;
      return mappedUser;
    } catch {
      await setAccessToken(null);
      currentUser = null;
      return null;
    }
  },

  async updateProfile(fullName: string, plotNumber?: string): Promise<User> {
    const updated = await apiRequest<ApiUser>('/user/profile', {
      method: 'PUT',
      body: { fullName, plotNumber },
    });
    const mappedUser = mapApiUser(updated);
    currentUser = mappedUser;
    return mappedUser;
  },

  async changePassword(payload: ChangePasswordPayload): Promise<User> {
    const updated = await apiRequest<ApiUser>('/user/password', {
      method: 'PUT',
      body: payload,
    });
    const mappedUser = mapApiUser(updated);
    currentUser = mappedUser;
    return mappedUser;
  },
};
