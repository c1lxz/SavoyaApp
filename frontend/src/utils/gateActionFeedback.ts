import { GateAction, GateActionResult } from '@/types';

const USER_MESSAGES: Record<
  GateAction,
  {
    success: string;
    error: string;
  }
> = {
  entry: {
    success: 'Въездной шлагбаум открыт',
    error: 'Не удалось открыть въездной шлагбаум',
  },
  exit: {
    success: 'Выездной шлагбаум открыт',
    error: 'Не удалось открыть выездной шлагбаум',
  },
  wicket_north: {
    success: 'Северная калитка открыта',
    error: 'Не удалось открыть северную калитку',
  },
  wicket_lake: {
    success: 'Калитка у озера открыта',
    error: 'Не удалось открыть калитку у озера',
  },
  wicket_admin: {
    success: 'Калитка у администрации открыта',
    error: 'Не удалось открыть калитку у администрации',
  },
  wicket_forest: {
    success: 'Лесная калитка открыта',
    error: 'Не удалось открыть лесную калитку',
  },
};

export const getGateActionFeedback = (result: GateActionResult, isAdmin: boolean): string => {
  if (!result.success && result.errorCode === 'open_cooldown' && result.message.trim()) {
    return result.message;
  }

  if (isAdmin && result.message.trim()) {
    return result.message;
  }

  const actionMessages = USER_MESSAGES[result.action];
  if (!actionMessages) {
    return result.message;
  }

  return result.success ? actionMessages.success : actionMessages.error;
};
