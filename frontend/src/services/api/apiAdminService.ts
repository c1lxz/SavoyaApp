import { apiRequest } from '@/services/api/httpClient';
import { AdminRequestItem, AdminRequestList, AdminRequestStatus } from '@/types';

type BackendAdminResident = {
  id: number;
  login?: string | null;
  full_name?: string | null;
  phone: string;
  plot_number?: string | null;
};

type BackendAdminRequestItem = {
  id: number;
  resident: BackendAdminResident;
  key_type: string;
  key_value: string;
  country_label?: string | null;
  phone_number?: string | null;
  access_point_ids: number[];
  gate_key_id?: number | null;
  is_permanent: boolean;
  is_courier: boolean;
  expires_at?: string | null;
  status: AdminRequestStatus;
  created_at: string;
  cancelled_at?: string | null;
  plot_number?: string | null;
};

type BackendAdminRequestList = {
  total: number;
  items: BackendAdminRequestItem[];
};

export type AdminRequestQuery = {
  search?: string;
  status?: AdminRequestStatus | 'all';
  keyType?: 'VehicleNumber' | 'Phone' | 'all';
  residentLogin?: string;
  limit?: number;
  offset?: number;
};

const mapAdminRequest = (item: BackendAdminRequestItem): AdminRequestItem => ({
  id: String(item.id),
  resident: {
    id: String(item.resident.id),
    login: item.resident.login ?? '',
    fullName: item.resident.full_name ?? '',
    phone: item.resident.phone ?? '',
    plotNumber: item.resident.plot_number ?? '',
  },
  keyType: item.key_type,
  keyValue: item.key_value,
  countryLabel: item.country_label ?? null,
  phoneNumber: item.phone_number ?? null,
  accessPointIds: item.access_point_ids ?? [],
  gateKeyId: item.gate_key_id ?? null,
  isPermanent: item.is_permanent,
  isCourier: item.is_courier,
  expiresAt: item.expires_at ?? null,
  status: item.status,
  createdAt: item.created_at,
  cancelledAt: item.cancelled_at ?? null,
  plotNumber: item.plot_number ?? '',
});

export const apiAdminService = {
  async getRequests(query: AdminRequestQuery = {}): Promise<AdminRequestList> {
    const params = new URLSearchParams();

    if (query.search?.trim()) {
      params.set('search', query.search.trim());
    }
    if (query.status && query.status !== 'all') {
      params.set('status', query.status);
    }
    if (query.keyType && query.keyType !== 'all') {
      params.set('key_type', query.keyType);
    }
    if (query.residentLogin?.trim()) {
      params.set('resident_login', query.residentLogin.trim());
    }
    if (query.limit) {
      params.set('limit', String(query.limit));
    }
    if (query.offset) {
      params.set('offset', String(query.offset));
    }

    const suffix = params.toString() ? `?${params.toString()}` : '';
    const result = await apiRequest<BackendAdminRequestList>(`/api/admin/requests${suffix}`);

    return {
      total: result.total,
      items: result.items.map(mapAdminRequest),
    };
  },
};
