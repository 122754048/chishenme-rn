export type MembershipPlan = 'free' | 'pro' | 'family';

export const UNLIMITED_QUOTA = -1;
export const DAILY_FREE_QUOTA = 3;

export interface SavedQuota {
  date: string;
  left: number;
}

export function getQuotaByPlan(plan: MembershipPlan): number {
  return plan === 'free' ? DAILY_FREE_QUOTA : UNLIMITED_QUOTA;
}

export function isUnlimitedQuota(left: number): boolean {
  return left === UNLIMITED_QUOTA;
}

export function getQuotaForToday(plan: MembershipPlan, todayKey: string, saved: SavedQuota | null): SavedQuota {
  const planQuota = getQuotaByPlan(plan);
  if (isUnlimitedQuota(planQuota)) {
    return { date: todayKey, left: UNLIMITED_QUOTA };
  }
  if (!saved || saved.date !== todayKey) {
    return { date: todayKey, left: planQuota };
  }
  return { date: todayKey, left: Math.max(0, saved.left) };
}

export function consumeQuota(left: number): number {
  if (isUnlimitedQuota(left)) return left;
  return Math.max(0, left - 1);
}

export function getResetQuotaForFree(todayKey: string, saved: SavedQuota | null): SavedQuota {
  if (!saved || saved.date !== todayKey) {
    return { date: todayKey, left: DAILY_FREE_QUOTA };
  }
  if (saved.left === UNLIMITED_QUOTA) {
    return { date: todayKey, left: DAILY_FREE_QUOTA };
  }
  return { date: todayKey, left: Math.max(0, Math.min(DAILY_FREE_QUOTA, saved.left)) };
}
