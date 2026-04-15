export type RequestState = 'idle' | 'loading' | 'success' | 'error';

export type User = {
  id: string;
  login: string;
  fullName: string;
  plotNumber: string;
  phoneNumber?: string;
  isAdmin: boolean;
};

export type AuthResult = {
  success: boolean;
  user?: User;
  error?: string;
  requiresProfileCompletion?: boolean;
};

export type CreatePassPayload = {
  carNumber?: string;
  residentName?: string;
  plotNumber: string;
  phoneNumber?: string;
  expiresAt: string | null;
  isPermanent: boolean;
  isCourier: boolean;
};

export type PassStatus = 'active' | 'expired' | 'permanent';

export type PassItem = {
  id: string;
  keyType: 'Phone' | 'VehicleNumber';
  keyValue: string;
  carNumber?: string | null;
  plotNumber: string;
  phoneNumber?: string | null;
  expiresAt: string | null;
  isPermanent: boolean;
  isCourier?: boolean;
  status: PassStatus;
  createdAt: string;
};

export type GateAction = 'entry' | 'exit' | 'wicket_north' | 'wicket_lake' | 'wicket_admin' | 'wicket_forest';

export type GateActionResult = {
  success: boolean;
  action: GateAction;
  message: string;
  timestamp: number;
};

export type AdminResidentSummary = {
  id: string;
  login: string;
  fullName: string;
  phone: string;
  plotNumber: string;
};

export type AdminRequestStatus = 'active' | 'expired' | 'permanent' | 'cancelled' | 'completed';

export type AdminRequestItem = {
  id: string;
  resident: AdminResidentSummary;
  keyType: 'Phone' | 'VehicleNumber' | string;
  keyValue: string;
  countryLabel?: string | null;
  phoneNumber?: string | null;
  accessPointIds: number[];
  gateKeyId?: number | null;
  isPermanent: boolean;
  isCourier: boolean;
  expiresAt: string | null;
  status: AdminRequestStatus;
  createdAt: string;
  cancelledAt: string | null;
  plotNumber: string;
};

export type AdminRequestList = {
  total: number;
  items: AdminRequestItem[];
};

export type AdminMonitorSource = 'app' | 'gate';

export type AdminMonitorEventItem = {
  id: string;
  source: AdminMonitorSource;
  createdAt: string;
  status: string;
  action: string;
  message?: string | null;
  actorUserId?: number | null;
  actorLogin?: string | null;
  actorName?: string | null;
  actorPhone?: string | null;
  accessPointId?: number | null;
  accessPointName?: string | null;
  keyType?: string | null;
  keyValue?: string | null;
  requestId?: string | null;
  appRequestId?: number | null;
  gateKeyId?: number | null;
  gateEventIndex?: number | null;
  gateEventCode?: number | null;
  gateUserPtr?: number | null;
  gateName?: string | null;
  gateOriginalName?: string | null;
  gateUnit?: string | null;
  details?: Record<string, unknown> | null;
};

export type AdminMonitorResponse = {
  total: number;
  items: AdminMonitorEventItem[];
  gateError?: string | null;
};
