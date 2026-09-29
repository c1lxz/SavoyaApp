import { AuthResult, ChangePasswordPayload, StaffRole, User } from '@/types';
import { apiRequest } from '@/services/api/httpClient';
import { getAccessToken, restoreAccessToken, setAccessToken } from '@/services/api/tokenStore';
import { unregisterNewsNotifications } from '@/services/newsNotifications';

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
  staffRole?: StaffRole | null;
  passwordChangeRequired?: boolean;
  passwordChangePromptRequired?: boolean;
};

type BackendUser = {
  login?: string | null;
  id: number;
  phone: string;
  name?: string | null;
  apartment?: string | null;
  is_admin?: boolean;
  staff_role?: StaffRole | null;
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
let currentUserToken: string | null = null;
let sessionGeneration = 0;
let userRequest = 0;
let signingOut = false;
let tokenWrites: Promise<void> = Promise.resolve();

const staleSession = () => new Error('Сессия изменилась. Повторите действие.');
const requireSession = (generation: number, token?: string | null) => {
  if (generation !== sessionGeneration || (token !== undefined && token !== getAccessToken())) throw staleSession();
};
const writeSessionToken = async (token: string | null, generation: number) => {
  // Keep asynchronous native storage writes in session order as well as JS state.
  tokenWrites = tokenWrites.catch(() => {}).then(async () => {
    requireSession(generation);
    await setAccessToken(token);
  });
  await tokenWrites;
  requireSession(generation, token);
};

const mapBackendUser = (user: BackendUser): User => ({
  id: String(user.id),
  login: user.login || user.phone,
  fullName: user.name ?? '',
  plotNumber: user.apartment ?? '',
  phoneNumber: user.phone ?? '',
  isAdmin: Boolean(user.is_admin),
  staffRole: user.staff_role,
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
  staffRole: user.staffRole,
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
    const generation = ++sessionGeneration;
    userRequest += 1;
    signingOut = false;
    currentUser = null;
    currentUserToken = null;
    await writeSessionToken(null, generation);
    const result = await apiRequest<CompatLoginResponse | BackendTokenResponse>('/auth/login', {
      method: 'POST',
      body: { login, password },
    });
    requireSession(generation);

    if ('token_type' in result && 'access_token' in result) {
      const mappedUser = mapBackendUser(result.user);
      await writeSessionToken(result.access_token, generation);
      currentUser = mappedUser;
      currentUserToken = result.access_token;
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
      await writeSessionToken(result.access_token, generation);
      currentUser = mappedUser;
      currentUserToken = result.access_token;
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
    const generation = ++sessionGeneration;
    userRequest += 1;
    signingOut = true;
    currentUser = null;
    currentUserToken = null;
    await unregisterNewsNotifications().catch(() => { /* Allow offline logout. Invalid tokens expire server-side. */ });
    // A newer login owns the token if notification revocation finished late.
    if (generation !== sessionGeneration) return;
    await writeSessionToken(null, generation);
    signingOut = false;
  },

  async getCurrentUser(forceRefresh = false): Promise<User | null> {
    const generation = sessionGeneration;
    if (signingOut) return null;
    await restoreAccessToken();
    requireSession(generation);
    const token = getAccessToken();
    if (!token) {
      currentUser = null;
      currentUserToken = null;
      return null;
    }

    if (currentUser && currentUserToken === token && !forceRefresh) {
      return currentUser;
    }

    const request = ++userRequest;
    try {
      const actual = await apiRequest<ApiUser>('/user/me');
      requireSession(generation, token);
      if (request !== userRequest) throw staleSession();
      const mappedUser = mapApiUser(actual);
      currentUser = mappedUser;
      currentUserToken = token;
      return mappedUser;
    } catch (error) {
      if (generation !== sessionGeneration || request !== userRequest || (getAccessToken() && getAccessToken() !== token)) throw staleSession();
      if (!getAccessToken()) {
        currentUser = null;
        currentUserToken = null;
        return null;
      }
      currentUser = null;
      currentUserToken = null;
      throw error;
    }
  },

  async updateProfile(fullName: string, plotNumber?: string): Promise<User> {
    const generation = sessionGeneration;
    const token = getAccessToken();
    const updated = await apiRequest<ApiUser>('/user/profile', {
      method: 'PUT',
      body: { fullName, plotNumber },
    });
    requireSession(generation, token);
    userRequest += 1;
    const mappedUser = mapApiUser(updated);
    currentUser = mappedUser;
    currentUserToken = token;
    return mappedUser;
  },

  async changePassword(payload: ChangePasswordPayload): Promise<User> {
    const generation = sessionGeneration;
    const token = getAccessToken();
    const updated = await apiRequest<ApiUser>('/user/password', {
      method: 'PUT',
      body: payload,
    });
    requireSession(generation, token);
    userRequest += 1;
    const mappedUser = mapApiUser(updated);
    currentUser = mappedUser;
    currentUserToken = token;
    return mappedUser;
  },
};
