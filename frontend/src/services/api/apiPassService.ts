import { CreatePassPayload, PassItem } from '@/types';
import { apiRequest } from '@/services/api/httpClient';

export const apiPassService = {
  async createPass(payload: CreatePassPayload): Promise<PassItem> {
    return apiRequest<PassItem>('/passes', {
      method: 'POST',
      body: payload,
    });
  },
  async getMyPasses(): Promise<PassItem[]> {
    return apiRequest<PassItem[]>('/passes/my');
  },
  async cancelPass(id: string): Promise<void> {
    await apiRequest<void>(`/passes/${id}`, { method: 'DELETE' });
  },
};

