import { create } from 'zustand';

import { mockPassService } from '@/services/passService';
import { CreatePassPayload, PassItem, RequestState } from '@/types';

type PassesStore = {
  passes: PassItem[];
  ownerUserId: string | null;
  loadState: RequestState;
  createState: RequestState;
  cancelState: RequestState;
  passesLastLoadedAt: number | null;
  passesCacheTtlMs: number;
  loadError: string | null;
  createError: string | null;
  cancelError: string | null;
  resetPasses: (ownerUserId?: string | null) => void;
  loadMyPasses: (options?: { force?: boolean }) => Promise<void>;
  createPass: (payload: CreatePassPayload) => Promise<boolean>;
  // Roadmap: wire cancelPass to UI action in MyPasses list.
  cancelPass: (id: string) => Promise<void>;
};

export const usePassesStore = create<PassesStore>((set, get) => ({
  passes: [],
  ownerUserId: null,
  loadState: 'idle',
  createState: 'idle',
  cancelState: 'idle',
  passesLastLoadedAt: null,
  passesCacheTtlMs: 45_000,
  loadError: null,
  createError: null,
  cancelError: null,
  resetPasses(ownerUserId = null) {
    set({
      passes: [],
      ownerUserId,
      loadState: 'idle',
      createState: 'idle',
      cancelState: 'idle',
      passesLastLoadedAt: null,
      loadError: null,
      createError: null,
      cancelError: null,
    });
  },
  async loadMyPasses(options) {
    const force = options?.force ?? false;
    const { passesLastLoadedAt, passesCacheTtlMs } = get();
    const hasFreshCache =
      !force &&
      passesLastLoadedAt !== null &&
      Date.now() - passesLastLoadedAt < passesCacheTtlMs;

    if (hasFreshCache) {
      set((state) => ({
        loadState: state.loadState === 'idle' ? 'success' : state.loadState,
        loadError: null,
      }));
      return;
    }

    set({ loadState: 'loading', loadError: null });
    try {
      const passes = await mockPassService.getMyPasses();
      set({ passes, loadState: 'success', passesLastLoadedAt: Date.now(), loadError: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка загрузки пропусков';
      set({ loadState: 'error', loadError: message });
    }
  },
  async createPass(payload) {
    set({ createState: 'loading', createError: null });
    try {
      const createdPass = await mockPassService.createPass(payload);
      set((state) => ({
        passes: [createdPass, ...state.passes.filter((item) => item.id !== createdPass.id)],
        createState: 'success',
        loadState: state.loadState === 'idle' ? 'success' : state.loadState,
        passesLastLoadedAt: Date.now(),
        createError: null,
      }));
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось создать пропуск';
      set({ createState: 'error', createError: message });
      return false;
    }
  },
  async cancelPass(id) {
    set({ cancelState: 'loading', cancelError: null });
    try {
      await mockPassService.cancelPass(id);
      set((state) => ({
        passes: state.passes.filter((item) => item.id !== id),
        cancelState: 'success',
        loadState: state.loadState === 'idle' ? 'success' : state.loadState,
        passesLastLoadedAt: Date.now(),
        cancelError: null,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось отменить пропуск';
      set({ cancelState: 'error', cancelError: message });
    }
  },
}));

