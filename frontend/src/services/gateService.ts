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
      entry: 'Шлагбаум въезда открыт',
      exit: 'Шлагбаум выезда открыт',
      wicket_north: 'Калитка Северная (СНТ Пальмира) открыта',
      wicket_lake: 'Калитка Озеро (СНТ Вартемяки) открыта',
      wicket_admin: 'Калитка у администрации открыта',
      wicket_forest: 'Калитка Лес открыта',
    };

    return {
      success,
      action: type,
      message: success ? messageByAction[type] : 'Не удалось выполнить команду открытия',
      timestamp: Date.now(),
    };
  },
};
