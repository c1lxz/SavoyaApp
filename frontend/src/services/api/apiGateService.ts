import { GateAction, GateActionResult } from '@/types';
import { apiRequest } from '@/services/api/httpClient';

export const apiGateService = {
  async openAction(type: GateAction): Promise<GateActionResult> {
    return apiRequest<GateActionResult>('/gates/open-action', {
      method: 'POST',
      body: { action: type },
    });
  },
};

