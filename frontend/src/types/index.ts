export type RequestState = 'idle' | 'loading' | 'success' | 'error';

export type User = {
  id: string;
  login: string;
  fullName: string;
  plotNumber: string;
};

export type AuthResult = {
  success: boolean;
  user?: User;
  error?: string;
  requiresProfileCompletion?: boolean;
};

export type CreatePassPayload = {
  carNumber: string;
  plotNumber: string;
  expiresAt: string | null;
  isPermanent: boolean;
};

export type PassStatus = 'active' | 'expired' | 'permanent';

export type PassItem = {
  id: string;
  carNumber: string;
  plotNumber: string;
  expiresAt: string | null;
  isPermanent: boolean;
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
