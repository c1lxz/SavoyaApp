import { create } from 'zustand';

import { mockPassService } from '@/services/passService';
import { CreatePassPayload, PassItem, RequestState } from '@/types';

type PassesStore = {
  passes: PassItem[];
  loadState: RequestState;
  createState: RequestState;
  cancelState: RequestState;
  error: string | null;
  loadMyPasses: () => Promise<void>;
  createPass: (payload: CreatePassPayload) => Promise<boolean>;
  cancelPass: (id: string) => Promise<void>;
};

export const usePassesStore = create<PassesStore>((set) => ({
  passes: [],
  loadState: 'idle',
  createState: 'idle',
  cancelState: 'idle',
  error: null,
  async loadMyPasses() {
    set({ loadState: 'loading', error: null });
    try {
      const passes = await mockPassService.getMyPasses();
      set({ passes, loadState: 'success' });
    } catch {
      set({ loadState: 'error', error: 'Ошибка сети' });
    }
  },
  async createPass(payload) {
    set({ createState: 'loading', error: null });
    try {
      await mockPassService.createPass(payload);
      const passes = await mockPassService.getMyPasses();
      set({ passes, createState: 'success' });
      return true;
    } catch {
      set({ createState: 'error', error: 'Не удалось создать пропуск' });
      return false;
    }
  },
  async cancelPass(id) {
    set({ cancelState: 'loading', error: null });
    try {
      await mockPassService.cancelPass(id);
      const passes = await mockPassService.getMyPasses();
      set({ passes, cancelState: 'success' });
    } catch {
      set({ cancelState: 'error', error: 'Не удалось отменить пропуск' });
    }
  },
}));

