import { create } from 'zustand';

import { mockGateService } from '@/services/gateService';
import { GateAction, GateActionResult, RequestState } from '@/types';

type GateStore = {
  gateState: RequestState;
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

const openByType = async (type: GateAction, set: (partial: Partial<GateStore>) => void) => {
  set({ gateState: 'loading', result: null, error: null });
  try {
    const result = await mockGateService.openAction(type);

    if (result.success) {
      set({ gateState: 'success', result, error: null });
      return;
    }

    set({ gateState: 'error', result, error: result.message });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Ошибка сети';
    set({ gateState: 'error', result: null, error: message });
  }
};

export const useGateStore = create<GateStore>((set) => ({
  gateState: 'idle',
  result: null,
  error: null,
  openEntry: () => openByType('entry', set),
  openExit: () => openByType('exit', set),
  openWicketNorth: () => openByType('wicket_north', set),
  openWicketLake: () => openByType('wicket_lake', set),
  openWicketAdmin: () => openByType('wicket_admin', set),
  openWicketForest: () => openByType('wicket_forest', set),
  resetGateState() {
    set({ gateState: 'idle', result: null, error: null });
  },
}));

