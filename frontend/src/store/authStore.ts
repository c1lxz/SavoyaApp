import { create } from 'zustand';

import { mockAuthService } from '@/services/authService';
import { usePassesStore } from '@/store/passesStore';
import { ChangePasswordPayload, RegisterAccountPayload, RegisterAccountResult, RequestState, User } from '@/types';

type AuthStore = {
  user: User | null;
  requiresProfileCompletion: boolean;
  shouldPromptPasswordChange: boolean;
  loginState: RequestState;
  logoutState: RequestState;
  restoreState: RequestState;
  profileState: RequestState;
  registerState: RequestState;
  passwordChangeState: RequestState;
  error: string | null;
  login: (login: string, password: string) => Promise<boolean>;
  registerAccount: (payload: RegisterAccountPayload) => Promise<RegisterAccountResult | null>;
  updateProfile: (fullName: string, plotNumber?: string) => Promise<boolean>;
  changePassword: (payload: ChangePasswordPayload) => Promise<boolean>;
  dismissPasswordChangePrompt: () => void;
  logout: () => Promise<void>;
  restoreSession: () => Promise<void>;
};

const resolvePasswordChangePrompt = (user: User | null) => Boolean(user && !user.isAdmin && user.passwordChangeRequired);

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  requiresProfileCompletion: false,
  shouldPromptPasswordChange: false,
  loginState: 'idle',
  logoutState: 'idle',
  restoreState: 'idle',
  profileState: 'idle',
  registerState: 'idle',
  passwordChangeState: 'idle',
  error: null,

  async login(login, password) {
    set({ loginState: 'loading', error: null });
    try {
      const result = await mockAuthService.login(login, password);

      if (result.success && result.user) {
        usePassesStore.getState().resetPasses(result.user.id);
        set({
          user: result.user,
          loginState: 'success',
          requiresProfileCompletion: !result.user.isAdmin && Boolean(result.requiresProfileCompletion),
          shouldPromptPasswordChange: resolvePasswordChangePrompt(result.user),
        });
        return true;
      }

      set({ loginState: 'error', error: result.error ?? 'Ошибка сети' });
      return false;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ loginState: 'error', error: message });
      return false;
    }
  },

  async registerAccount(payload) {
    set({ registerState: 'loading', error: null });
    try {
      const result = await mockAuthService.registerAccount(payload);
      set({ registerState: 'success' });
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ registerState: 'error', error: message });
      return null;
    }
  },

  async updateProfile(fullName, plotNumber) {
    set({ profileState: 'loading', error: null });
    try {
      const updated = await mockAuthService.updateProfile(fullName, plotNumber);
      set({
        user: updated,
        profileState: 'success',
        requiresProfileCompletion: false,
        shouldPromptPasswordChange: resolvePasswordChangePrompt(updated),
      });
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ profileState: 'error', error: message });
      return false;
    }
  },

  async changePassword(payload) {
    set({ passwordChangeState: 'loading', error: null });
    try {
      const updated = await mockAuthService.changePassword(payload);
      set({
        user: updated,
        passwordChangeState: 'success',
        shouldPromptPasswordChange: false,
      });
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ passwordChangeState: 'error', error: message });
      return false;
    }
  },

  dismissPasswordChangePrompt() {
    set({ shouldPromptPasswordChange: false });
  },

  async logout() {
    set({ logoutState: 'loading', error: null });
    try {
      await mockAuthService.logout();
      usePassesStore.getState().resetPasses(null);
      set({
        user: null,
        logoutState: 'success',
        requiresProfileCompletion: false,
        shouldPromptPasswordChange: false,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ logoutState: 'error', error: message });
    }
  },

  async restoreSession() {
    set({ restoreState: 'loading', error: null });
    try {
      const user = await mockAuthService.getCurrentUser();
      usePassesStore.getState().resetPasses(user?.id ?? null);
      set({
        user,
        restoreState: 'success',
        requiresProfileCompletion: user ? !user.isAdmin && !Boolean(user.fullName.trim()) : false,
        shouldPromptPasswordChange: resolvePasswordChangePrompt(user),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ restoreState: 'error', error: message, user: null, shouldPromptPasswordChange: false });
    }
  },
}));
