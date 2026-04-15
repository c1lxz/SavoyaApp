import { apiRequest } from '@/services/api/httpClient';
import { AdminMonitorEventItem, AdminMonitorResponse, AdminRequestItem, AdminRequestList, AdminRequestStatus } from '@/types';

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

type BackendAdminMonitorEventItem = {
  id: string;
  source: 'app' | 'gate';
  created_at: string;
  status: string;
  action: string;
  message?: string | null;
  actor_user_id?: number | null;
  actor_login?: string | null;
  actor_name?: string | null;
  actor_phone?: string | null;
  access_point_id?: number | null;
  access_point_name?: string | null;
  key_type?: string | null;
  key_value?: string | null;
  request_id?: string | null;
  app_request_id?: number | null;
  gate_key_id?: number | null;
  gate_event_index?: number | null;
  gate_event_code?: number | null;
  gate_user_ptr?: number | null;
  gate_name?: string | null;
  gate_original_name?: string | null;
  gate_unit?: string | null;
  details?: Record<string, unknown> | null;
};

type BackendAdminMonitorResponse = {
  total: number;
  items: BackendAdminMonitorEventItem[];
  gate_error?: string | null;
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

const mapMonitorEvent = (item: BackendAdminMonitorEventItem): AdminMonitorEventItem => ({
  id: item.id,
  source: item.source,
  createdAt: item.created_at,
  status: item.status,
  action: item.action,
  message: item.message ?? null,
  actorUserId: item.actor_user_id ?? null,
  actorLogin: item.actor_login ?? null,
  actorName: item.actor_name ?? null,
  actorPhone: item.actor_phone ?? null,
  accessPointId: item.access_point_id ?? null,
  accessPointName: item.access_point_name ?? null,
  keyType: item.key_type ?? null,
  keyValue: item.key_value ?? null,
  requestId: item.request_id ?? null,
  appRequestId: item.app_request_id ?? null,
  gateKeyId: item.gate_key_id ?? null,
  gateEventIndex: item.gate_event_index ?? null,
  gateEventCode: item.gate_event_code ?? null,
  gateUserPtr: item.gate_user_ptr ?? null,
  gateName: item.gate_name ?? null,
  gateOriginalName: item.gate_original_name ?? null,
  gateUnit: item.gate_unit ?? null,
  details: item.details ?? null,
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

  async getMonitor(limit = 120): Promise<AdminMonitorResponse> {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    const result = await apiRequest<BackendAdminMonitorResponse>(`/api/admin/monitor?${params.toString()}`);

    return {
      total: result.total,
      items: result.items.map(mapMonitorEvent),
      gateError: result.gate_error ?? null,
    };
  },
};
