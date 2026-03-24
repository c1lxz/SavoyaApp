import { CreatePassPayload, PassItem, PassStatus } from '@/types';

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
    // TODO: POST /passes
    // TODO: backend should calculate status, not frontend
    const draft = {
      id: Date.now().toString(36),
      carNumber: payload.carNumber.toUpperCase(),
      plotNumber: payload.plotNumber,
      expiresAt: payload.expiresAt,
      isPermanent: payload.isPermanent,
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
    // TODO: GET /passes/my
    return [...store].map((item) => {
      const { status: _status, ...rest } = item;
      return { ...rest, status: resolveStatus(rest) };
    });
  },
  async cancelPass(id: string) {
    // TODO: DELETE /passes/{id}
    const index = store.findIndex((item) => item.id === id);
    if (index >= 0) {
      store.splice(index, 1);
    }
  },
};

