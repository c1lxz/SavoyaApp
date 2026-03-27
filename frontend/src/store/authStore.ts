import { create } from 'zustand';

import { mockAuthService } from '@/services/authService';
import { RequestState, User } from '@/types';

type AuthStore = {
  user: User | null;
  loginState: RequestState;
  logoutState: RequestState;
  restoreState: RequestState;
  error: string | null;
  login: (login: string, password: string) => Promise<boolean>;
  // Roadmap: wire logout to UI entrypoint.
  logout: () => Promise<void>;
  // Roadmap: call restoreSession during app bootstrap.
  restoreSession: () => Promise<void>;
};

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  loginState: 'idle',
  logoutState: 'idle',
  restoreState: 'idle',
  error: null,
  async login(login, password) {
    set({ loginState: 'loading', error: null });
    try {
      const result = await mockAuthService.login(login, password);

      if (result.success && result.user) {
        set({ user: result.user, loginState: 'success' });
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
  async logout() {
    set({ logoutState: 'loading', error: null });
    try {
      await mockAuthService.logout();
      set({ user: null, logoutState: 'success' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ logoutState: 'error', error: message });
    }
  },
  async restoreSession() {
    set({ restoreState: 'loading', error: null });
    try {
      const user = await mockAuthService.getCurrentUser();
      set({ user, restoreState: 'success' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка сети';
      set({ restoreState: 'error', error: message, user: null });
    }
  },
}));

