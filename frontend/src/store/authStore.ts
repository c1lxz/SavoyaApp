import { create } from 'zustand';

import { mockAuthService } from '@/services/authService';
import { usePassesStore } from '@/store/passesStore';
import { RequestState, User } from '@/types';

type AuthStore = {
  user: User | null;
  requiresProfileCompletion: boolean;
  loginState: RequestState;
  logoutState: RequestState;
  restoreState: RequestState;
  profileState: RequestState;
  error: string | null;
  login: (login: string, password: string) => Promise<boolean>;
  updateProfile: (fullName: string, plotNumber?: string) => Promise<boolean>;
  // Roadmap: wire logout to UI entrypoint.
  logout: () => Promise<void>;
  // Roadmap: call restoreSession during app bootstrap.
  restoreSession: () => Promise<void>;
};

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  requiresProfileCompletion: false,
  loginState: 'idle',
  logoutState: 'idle',
  restoreState: 'idle',
  profileState: 'idle',
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
          requiresProfileCompletion: Boolean(result.requiresProfileCompletion),
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
  async updateProfile(fullName, plotNumber) {
    set({ profileState: 'loading', error: null });
    try {
      const updated = await mockAuthService.updateProfile(fullName, plotNumber);
      set({
        user: updated,
        profileState: 'success',
        requiresProfileCompletion: false,
      });
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ profileState: 'error', error: message });
      return false;
    }
  },
  async logout() {
    set({ logoutState: 'loading', error: null });
    try {
      await mockAuthService.logout();
      usePassesStore.getState().resetPasses(null);
      set({ user: null, logoutState: 'success', requiresProfileCompletion: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ logoutState: 'error', error: message });
    }
  },
  async restoreSession() {
    set({ restoreState: 'loading', error: null });
    try {
      const user = null;
      usePassesStore.getState().resetPasses(null);
      set({
        user,
        restoreState: 'success',
        requiresProfileCompletion: user ? !Boolean(user.fullName.trim()) : false,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ restoreState: 'error', error: message, user: null });
    }
  },
}));

