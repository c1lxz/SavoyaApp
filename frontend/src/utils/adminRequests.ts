import { AdminRequestItem } from '@/types';
import { formatDateTime } from '@/utils/date';
import { formatVehicleLabel } from '@/utils/vehicleCountry';

export const formatAdminRequestKey = (item: AdminRequestItem): string => {
  if (item.keyType === 'VehicleNumber') {
    return formatVehicleLabel(item.keyValue, item.countryLabel);
  }
  return item.keyValue;
};

export const formatPassPurpose = (purpose: AdminRequestItem['passPurpose'], isCourier?: boolean): string | null => {
  if (purpose === 'courier') {
    return 'Курьер';
  }
  if (purpose === 'taxi') {
    return 'Такси';
  }
  if (purpose === 'other') {
    return 'Другое';
  }
  return isCourier ? 'Курьер' : null;
};

export const formatRequestForCopy = (item: AdminRequestItem): string => {
  const lines = [
    `Заявка #${item.id}`,
    `Создана: ${formatDateTime(item.createdAt)}`,
    `Статус: ${item.status}`,
    `Тип: ${item.keyType === 'VehicleNumber' ? 'Номер ТС' : 'Телефон'}`,
    `Значение: ${formatAdminRequestKey(item)}`,
    `Собственник: ${item.resident.fullName || '-'}`,
    `Логин: ${item.resident.login || '-'}`,
    `Телефон жителя: ${item.resident.phone || '-'}`,
    `Участок жителя: ${item.resident.plotNumber || '-'}`,
    `Участок в заявке: ${item.plotNumber || '-'}`,
    `Контактный телефон: ${item.phoneNumber || '-'}`,
    `Точки доступа: ${item.accessPointIds.length ? item.accessPointIds.join(', ') : '-'}`,
    `Gate key ID: ${item.gateKeyId ?? '-'}`,
    `Постоянный: ${item.isPermanent ? 'Да' : 'Нет'}`,
    `Тип пропуска: ${formatPassPurpose(item.passPurpose, item.isCourier) ?? '-'}`,
  ];

  if (item.expiresAt) {
    lines.push(`Действует до: ${formatDateTime(item.expiresAt)}`);
  }

  if (item.cancelledAt) {
    lines.push(`Отменена: ${formatDateTime(item.cancelledAt)}`);
  }

  return lines.join('\n');
};
