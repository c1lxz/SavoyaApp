import { create } from 'zustand';

import { mockGateService } from '@/services/gateService';
import { useAuthStore } from '@/store/authStore';
import { GateAction, GateActionResult, RequestState } from '@/types';

type GateStore = {
  gateState: RequestState;
  loadingAction: GateAction | null;
  result: GateActionResult | null;
  error: string | null;
  openEntry: () => Promise<void>;
  openExit: () => Promise<void>;
  openWicketNorth: () => Promise<void>;
  openWicketLake: () => Promise<void>;
  openWicketAdmin: () => Promise<void>;
  openWicketForest: () => Promise<void>;
  resetGateState: () => void;
};

const openByType = async (
  type: GateAction,
  set: (partial: Partial<GateStore>) => void,
  get: () => GateStore,
) => {
  if (get().gateState === 'loading') {
    return;
  }

  set({ gateState: 'loading', loadingAction: type, result: null, error: null });
  const sessionIsValid = await useAuthStore.getState().validateSession();
  if (!sessionIsValid || !useAuthStore.getState().user) {
    set({ gateState: 'idle', loadingAction: null, result: null, error: null });
    return;
  }

  try {
    const result = await mockGateService.openAction(type);

    if (result.success) {
      set({ gateState: 'success', loadingAction: null, result, error: null });
      return;
    }

    set({ gateState: 'error', loadingAction: null, result, error: null });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Ошибка сети';
    set({ gateState: 'error', loadingAction: null, result: null, error: message });
  }
};

export const useGateStore = create<GateStore>((set, get) => ({
  gateState: 'idle',
  loadingAction: null,
  result: null,
  error: null,
  openEntry: () => openByType('entry', set, get),
  openExit: () => openByType('exit', set, get),
  openWicketNorth: () => openByType('wicket_north', set, get),
  openWicketLake: () => openByType('wicket_lake', set, get),
  openWicketAdmin: () => openByType('wicket_admin', set, get),
  openWicketForest: () => openByType('wicket_forest', set, get),
  resetGateState() {
    set({ gateState: 'idle', loadingAction: null, result: null, error: null });
  },
}));
