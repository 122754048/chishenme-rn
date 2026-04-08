import { storage } from '../storage';

type Plan = 'free' | 'pro' | 'family';
type PaidPlan = 'pro' | 'family';

const API_BASE = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
const BOOTSTRAP_PASSWORD = process.env.EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD?.trim();

function isEnabled() {
  return Boolean(API_BASE);
}

async function request<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  if (!API_BASE) throw new Error('Backend API URL is not configured');
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  return (await res.json()) as T;
}

function randomUserId() {
  return `rn_${Math.random().toString(36).slice(2, 10)}`;
}

async function getOrCreateUserId() {
  const cached = await storage.getBackendUserId();
  if (cached) return cached;
  const created = randomUserId();
  await storage.setBackendUserId(created);
  return created;
}

export const backendApi = {
  isEnabled,

  async ensureToken(): Promise<string | null> {
    if (!isEnabled()) return null;
    if (!BOOTSTRAP_PASSWORD) return null;
    const cached = await storage.getBackendToken();
    if (cached) return cached;

    const userId = await getOrCreateUserId();

    try {
      const registered = await request<{ access_token: string }>('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, password: BOOTSTRAP_PASSWORD }),
      });
      await storage.setBackendToken(registered.access_token);
      return registered.access_token;
    } catch {
      const loggedIn = await request<{ access_token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, password: BOOTSTRAP_PASSWORD }),
      });
      await storage.setBackendToken(loggedIn.access_token);
      return loggedIn.access_token;
    }
  },

  async getQuotaToday(token: string): Promise<{ date: string; left: number }> {
    return request('/quota/today', { method: 'GET' }, token);
  },

  async consumeQuota(token: string): Promise<{ allowed: boolean; date: string; left: number }> {
    const idem = `q-${Date.now()}`;
    return request('/quota/consume', { method: 'POST', headers: { 'Idempotency-Key': idem }, body: JSON.stringify({}) }, token);
  },

  async getMembership(token: string): Promise<{ plan: Plan }> {
    return request('/membership/me', { method: 'GET' }, token);
  },

  async createOrder(token: string, plan: PaidPlan): Promise<{ order_no: string; status: 'created'; pay_url: string }> {
    const idem = `o-${Date.now()}`;
    return request('/billing/alipay/create-order', {
      method: 'POST',
      headers: { 'Idempotency-Key': idem },
      body: JSON.stringify({ plan }),
    }, token);
  },

  async getOrder(token: string, orderNo: string): Promise<{ order_no: string; status: 'created' | 'paid' | 'failed' }> {
    return request(`/billing/orders/${orderNo}`, { method: 'GET' }, token);
  },
};
