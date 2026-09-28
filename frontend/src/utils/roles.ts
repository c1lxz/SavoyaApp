import type { StaffRole, User } from '@/types';

type RoleUser = Pick<User, 'isAdmin' | 'staffRole'> | null | undefined;

export const isStaff = (user: RoleUser): boolean => Boolean(user?.isAdmin);

export const getStaffRole = (user: RoleUser): StaffRole | null => {
  if (!user?.isAdmin) return null;
  // Older API releases only identify administrators with isAdmin.
  if (user.staffRole == null) return 'administration';
  return user.staffRole === 'administration' || user.staffRole === 'dispatcher' ? user.staffRole : null;
};

export const canManageNews = (user: RoleUser): boolean => getStaffRole(user) === 'administration';
export const canRegisterUsers = canManageNews;
export const canManageStaff = canManageNews;
export const staffRoleLabel = (user: RoleUser): string =>
  getStaffRole(user) === 'administration' ? 'Администрация' : getStaffRole(user) === 'dispatcher' ? 'Диспетчер' : 'Сотрудник';
