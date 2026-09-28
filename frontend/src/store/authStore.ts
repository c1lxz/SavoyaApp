import { create } from 'zustand';

import { mockAuthService } from '@/services/authService';
import { setUnauthorizedHandler } from '@/services/api/httpClient';
import { usePassesStore } from '@/store/passesStore';
import { ChangePasswordPayload, RequestState, User } from '@/types';

type AuthStore = {
  user: User | null;
  requiresProfileCompletion: boolean;
  shouldPromptPasswordChange: boolean;
  loginState: RequestState;
  logoutState: RequestState;
  restoreState: RequestState;
  profileState: RequestState;
  passwordChangeState: RequestState;
  error: string | null;
  login: (login: string, password: string) => Promise<boolean>;
  updateProfile: (fullName: string, plotNumber?: string) => Promise<boolean>;
  changePassword: (payload: ChangePasswordPayload) => Promise<boolean>;
  dismissPasswordChangePrompt: () => void;
  logout: () => Promise<void>;
  restoreSession: () => Promise<void>;
  validateSession: () => Promise<boolean>;
};

const BLOCKED_ACCOUNT_MESSAGE =
  'Ваш аккаунт был заблокирован. Пожалуйста обратитесь к администрации по этому вопросу';

const normalizeAuthError = (message: string | null | undefined): string => {
  const fallback = message || 'Ошибка сети';
  if (fallback === 'User is inactive' || fallback === 'Пользователь деактивирован' || fallback === 'inactive_user') {
    return BLOCKED_ACCOUNT_MESSAGE;
  }
  return fallback;
};

const resolvePasswordChangePrompt = (user: User | null) =>
  Boolean(user && (user.passwordChangePromptRequired ?? user.passwordChangeRequired));

let sessionGeneration = 0;
let userRequest = 0;

export const useAuthStore = create<AuthStore>((set, get) => ({
  user: null,
  requiresProfileCompletion: false,
  shouldPromptPasswordChange: false,
  loginState: 'idle',
  logoutState: 'idle',
  restoreState: 'idle',
  profileState: 'idle',
  passwordChangeState: 'idle',
  error: null,

  async login(login, password) {
    const generation = ++sessionGeneration;
    userRequest += 1;
    set({ loginState: 'loading', restoreState: 'success', error: null });
    try {
      const result = await mockAuthService.login(login, password);
      if (generation !== sessionGeneration) return false;

      if (result.success && result.user) {
        usePassesStore.getState().resetPasses(result.user.id);
        set({
          user: result.user,
          loginState: 'success',
          logoutState: 'idle',
          profileState: 'idle',
          passwordChangeState: 'idle',
          requiresProfileCompletion: !result.user.isAdmin && Boolean(result.requiresProfileCompletion),
          shouldPromptPasswordChange: resolvePasswordChangePrompt(result.user),
        });
        return true;
      }

      set({ loginState: 'error', error: normalizeAuthError(result.error) });
      return false;
    } catch (error) {
      if (generation !== sessionGeneration) return false;
      const message = normalizeAuthError(error instanceof Error ? error.message : null);
      set({ loginState: 'error', error: message });
      return false;
    }
  },

  async updateProfile(fullName, plotNumber) {
    const generation = sessionGeneration;
    const userId = get().user?.id;
    set({ profileState: 'loading', error: null });
    try {
      const updated = await mockAuthService.updateProfile(fullName, plotNumber);
      if (generation !== sessionGeneration || get().user?.id !== userId) return false;
      userRequest += 1;
      set({
        user: updated,
        profileState: 'success',
        requiresProfileCompletion: false,
        shouldPromptPasswordChange: resolvePasswordChangePrompt(updated),
      });
      return true;
    } catch (error) {
      if (generation !== sessionGeneration || get().user?.id !== userId) return false;
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ profileState: 'error', error: message });
      return false;
    }
  },

  async changePassword(payload) {
    const generation = sessionGeneration;
    const userId = get().user?.id;
    set({ passwordChangeState: 'loading', error: null });
    try {
      const updated = await mockAuthService.changePassword(payload);
      if (generation !== sessionGeneration || get().user?.id !== userId) return false;
      userRequest += 1;
      set({
        user: updated,
        passwordChangeState: 'success',
        shouldPromptPasswordChange: false,
      });
      return true;
    } catch (error) {
      if (generation !== sessionGeneration || get().user?.id !== userId) return false;
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ passwordChangeState: 'error', error: message });
      return false;
    }
  },

  dismissPasswordChangePrompt() {
    set((state) => ({
      shouldPromptPasswordChange: false,
      user: state.user ? { ...state.user, passwordChangePromptRequired: false } : state.user,
    }));
  },

  async logout() {
    clearSessionState();
    const generation = sessionGeneration;
    set({ logoutState: 'loading', error: null });
    try {
      await mockAuthService.logout();
      if (generation !== sessionGeneration) return;
      set({
        logoutState: 'success',
      });
    } catch (error) {
      if (generation !== sessionGeneration) return;
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ logoutState: 'error', error: message });
    }
  },

  async restoreSession() {
    const generation = sessionGeneration;
    const request = ++userRequest;
    set({ restoreState: 'loading', error: null });
    try {
      const user = await mockAuthService.getCurrentUser();
      if (generation !== sessionGeneration || request !== userRequest) return;
      usePassesStore.getState().resetPasses(user?.id ?? null);
      set({
        user,
        restoreState: 'success',
        requiresProfileCompletion: user ? !user.isAdmin && !Boolean(user.fullName.trim()) : false,
        shouldPromptPasswordChange: resolvePasswordChangePrompt(user),
      });
    } catch (error) {
      if (generation !== sessionGeneration || request !== userRequest) return;
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ restoreState: 'error', error: message, user: null, shouldPromptPasswordChange: false });
    }
  },

  async validateSession() {
    if (!get().user || get().loginState === 'loading' || get().logoutState === 'loading') {
      return false;
    }

    const generation = sessionGeneration;
    const userId = get().user?.id;
    const request = ++userRequest;
    try {
      const user = await mockAuthService.getCurrentUser(true);
      if (generation !== sessionGeneration || request !== userRequest || get().user?.id !== userId) return Boolean(get().user);
      if (user && user.id !== userId) return Boolean(get().user);
      if (!user) {
        clearSessionState();
        return false;
      }

      set({
        user,
        requiresProfileCompletion: !user.isAdmin && !Boolean(user.fullName.trim()),
        shouldPromptPasswordChange: resolvePasswordChangePrompt(user),
      });
      return true;
    } catch {
      // Keep the current session on transient network failures.
      return Boolean(get().user);
    }
  },
}));

function clearSessionState(): void {
  sessionGeneration += 1;
  userRequest += 1;
  usePassesStore.getState().resetPasses(null);
  useAuthStore.setState({
    user: null,
    requiresProfileCompletion: false,
    shouldPromptPasswordChange: false,
    loginState: 'idle',
    logoutState: 'idle',
    restoreState: 'success',
    profileState: 'idle',
    passwordChangeState: 'idle',
    error: null,
  });
}

setUnauthorizedHandler(() => {
  clearSessionState();
});
