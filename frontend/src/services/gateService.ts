import { GateAction, GateActionResult } from '@/types';
import { apiGateService } from '@/services/api/apiGateService';
import { USE_REAL_API } from '@/services/api/config';

export interface GateService {
  openAction(type: GateAction): Promise<GateActionResult>;
}

const sleep = (minMs: number, maxMs: number) =>
  new Promise<void>((resolve) => {
    const timeout = Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
    setTimeout(resolve, timeout);
  });

export const mockGateService: GateService = {
  async openAction(type) {
    if (USE_REAL_API) {
      return apiGateService.openAction(type);
    }

    await sleep(500, 1200);

    const success = Math.random() <= 0.9;
    const messageByAction: Record<GateAction, string> = {
      entry: 'Команда на въезд отправлена. Факт открытия не подтверждён.',
      exit: 'Команда на выезд отправлена. Факт открытия не подтверждён.',
      wicket_north: 'Команда на открытие северной калитки отправлена.',
      wicket_lake: 'Команда на открытие калитки у озера отправлена.',
      wicket_admin: 'Команда на открытие калитки у администрации отправлена.',
      wicket_forest: 'Команда на открытие калитки у леса отправлена.',
    };

    return {
      success,
      action: type,
      message: success ? messageByAction[type] : 'Не удалось выполнить команду открытия',
      timestamp: Date.now(),
    };
  },
};
