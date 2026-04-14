import { Platform } from 'react-native';
import Purchases, { PURCHASE_TYPE, type CustomerInfo, type PurchasesStoreProduct } from 'react-native-purchases';

export type MembershipPlan = 'free' | 'pro' | 'family';
export type PaidMembershipPlan = Exclude<MembershipPlan, 'free'>;

export interface PurchaseResult {
  plan: MembershipPlan;
  message: string;
}

const IOS_API_KEY = process.env.EXPO_PUBLIC_RC_IOS_API_KEY?.trim();
const ENTITLEMENT_ID = process.env.EXPO_PUBLIC_RC_ENTITLEMENT_ID?.trim() || 'premium';
const PRO_PRODUCT_ID = process.env.EXPO_PUBLIC_RC_PRO_PRODUCT_ID?.trim() || 'teller.pro.monthly';
const FAMILY_PRODUCT_ID = process.env.EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID?.trim() || 'teller.family.monthly';

let configured = false;
let configuredUserId: string | undefined;

function isIapAvailable() {
  return Platform.OS === 'ios' && Boolean(IOS_API_KEY);
}

function productIdForPlan(plan: PaidMembershipPlan) {
  return plan === 'family' ? FAMILY_PRODUCT_ID : PRO_PRODUCT_ID;
}

function planFromProductId(productId: string | null | undefined): MembershipPlan {
  if (productId === FAMILY_PRODUCT_ID) return 'family';
  if (productId === PRO_PRODUCT_ID) return 'pro';
  return 'free';
}

function planFromCustomerInfo(customerInfo: CustomerInfo): MembershipPlan {
  const entitlement = customerInfo.entitlements.active[ENTITLEMENT_ID];
  if (!entitlement?.isActive) return 'free';
  return planFromProductId(entitlement.productIdentifier);
}

async function configure(appUserId?: string) {
  if (!isIapAvailable()) {
    configured = false;
    return;
  }
  if (configured && configuredUserId === appUserId) return;
  Purchases.configure({
    apiKey: IOS_API_KEY!,
    appUserID: appUserId,
  });
  configured = true;
  configuredUserId = appUserId;
}

async function requireConfigured(appUserId?: string) {
  if (!isIapAvailable()) {
    throw new Error('Apple In-App Purchase is not configured yet for this build.');
  }
  await configure(appUserId);
}

async function findProduct(plan: PaidMembershipPlan): Promise<PurchasesStoreProduct> {
  const productId = productIdForPlan(plan);
  const products = await Purchases.getProducts([productId], PURCHASE_TYPE.SUBS);
  const product = products.find((item) => item.identifier === productId);
  if (!product) {
    throw new Error('The subscription product is not available yet. Check App Store Connect and RevenueCat configuration.');
  }
  return product;
}

function normalizePurchaseError(error: unknown): Error {
  const anyError = error as { userCancelled?: boolean; message?: string } | null;
  if (anyError?.userCancelled) {
    return new Error('Purchase canceled. Your membership did not change.');
  }
  if (anyError?.message) {
    return new Error(anyError.message);
  }
  return new Error('The purchase could not be completed right now. Please try again in a moment.');
}

export const subscriptionService = {
  isIapAvailable,

  configure,

  async syncCustomerPlan(appUserId?: string): Promise<MembershipPlan | null> {
    if (!isIapAvailable()) return null;
    try {
      await requireConfigured(appUserId);
      const customerInfo = await Purchases.getCustomerInfo();
      return planFromCustomerInfo(customerInfo);
    } catch (error) {
      console.warn('[Teller]', 'Failed to sync RevenueCat customer info:', error);
      return null;
    }
  },

  async purchase(plan: PaidMembershipPlan, appUserId?: string): Promise<PurchaseResult> {
    try {
      await requireConfigured(appUserId);
      const product = await findProduct(plan);
      const { customerInfo } = await Purchases.purchaseStoreProduct(product);
      const resolvedPlan = planFromCustomerInfo(customerInfo);
      if (resolvedPlan === 'free') {
        throw new Error('Purchase finished, but we could not confirm an active entitlement yet. Try Restore Purchases in a moment.');
      }
      return { plan: resolvedPlan, message: 'Subscription active. Your premium access is now live.' };
    } catch (error) {
      throw normalizePurchaseError(error);
    }
  },

  async restore(appUserId?: string): Promise<PurchaseResult> {
    try {
      await requireConfigured(appUserId);
      const customerInfo = await Purchases.restorePurchases();
      const plan = planFromCustomerInfo(customerInfo);
      if (plan === 'free') {
        return { plan, message: 'No active purchases were found to restore.' };
      }
      return { plan, message: 'Purchases restored. Your membership is active again.' };
    } catch (error) {
      throw normalizePurchaseError(error);
    }
  },
};
