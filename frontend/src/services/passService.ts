import { CreatePassPayload, PassItem, PassStatus } from '@/types';
import { apiPassService } from '@/services/api/apiPassService';
import { mockAuthService } from '@/services/authService';
import { USE_REAL_API } from '@/services/api/config';

export interface PassService {
  createPass(payload: CreatePassPayload): Promise<PassItem>;
  getMyPasses(): Promise<PassItem[]>;
  cancelPass(id: string): Promise<void>;
}

const store: PassItem[] = [];

const resolveStatus = (pass: Omit<PassItem, 'status'>): PassStatus => {
  if (pass.isPermanent) {
    return 'permanent';
  }

  if (pass.expiresAt && new Date(pass.expiresAt).getTime() < Date.now()) {
    return 'expired';
  }

  return 'active';
};

export const mockPassService: PassService = {
  async createPass(payload) {
    if (USE_REAL_API) {
      return apiPassService.createPass(payload);
    }

    const currentUser = await mockAuthService.getCurrentUser();
    const phoneNumber = payload.phoneNumber ?? currentUser?.phoneNumber ?? null;
    const keyType: PassItem['keyType'] = payload.carNumber ? 'VehicleNumber' : 'Phone';
    const keyValue = payload.carNumber ?? phoneNumber ?? '';

    const draft = {
      id: Date.now().toString(36),
      keyType,
      keyValue,
      carNumber: payload.carNumber?.toUpperCase() ?? null,
      plotNumber: payload.plotNumber,
      phoneNumber,
      expiresAt: payload.expiresAt,
      isPermanent: payload.isPermanent,
      isCourier: payload.isCourier,
      createdAt: new Date().toISOString(),
    };

    const item: PassItem = {
      ...draft,
      status: resolveStatus(draft),
    };

    store.unshift(item);

    return item;
  },
  async getMyPasses() {
    if (USE_REAL_API) {
      return apiPassService.getMyPasses();
    }

    return [...store].map((item) => {
      const { status: _status, ...rest } = item;
      return { ...rest, status: resolveStatus(rest) };
    });
  },
  async cancelPass(id: string) {
    if (USE_REAL_API) {
      await apiPassService.cancelPass(id);
      return;
    }

    const index = store.findIndex((item) => item.id === id);
    if (index >= 0) {
      store.splice(index, 1);
    }
  },
};
