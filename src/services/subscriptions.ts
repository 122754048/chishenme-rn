import { Platform } from 'react-native';
import Purchases, {
  PURCHASE_TYPE,
  type CustomerInfo,
  type PurchasesStoreProduct,
} from 'react-native-purchases';

export type MembershipPlan = 'free' | 'pro' | 'family';
export type PaidMembershipPlan = Exclude<MembershipPlan, 'free'>;

export interface PurchaseResult {
  plan: MembershipPlan;
  message: string;
}

const IOS_API_KEY = process.env.EXPO_PUBLIC_RC_IOS_API_KEY?.trim();
const ENTITLEMENT_ID = process.env.EXPO_PUBLIC_RC_ENTITLEMENT_ID?.trim() || 'premium';
const PRO_PRODUCT_ID = process.env.EXPO_PUBLIC_RC_PRO_PRODUCT_ID?.trim() || 'chishenme.pro.monthly';
const FAMILY_PRODUCT_ID = process.env.EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID?.trim() || 'chishenme.family.monthly';

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
    throw new Error('当前 iOS 内购尚未配置，请稍后再试。');
  }
  await configure(appUserId);
}

async function findProduct(plan: PaidMembershipPlan): Promise<PurchasesStoreProduct> {
  const productId = productIdForPlan(plan);
  const products = await Purchases.getProducts([productId], PURCHASE_TYPE.SUBS);
  const product = products.find((item) => item.identifier === productId);
  if (!product) {
    throw new Error('订阅商品暂不可用，请确认 App Store Connect 与 RevenueCat 配置。');
  }
  return product;
}

function normalizePurchaseError(error: unknown): Error {
  const anyError = error as { userCancelled?: boolean; message?: string; code?: string } | null;
  if (anyError?.userCancelled) {
    return new Error('已取消购买，会员状态未发生变化。');
  }
  if (anyError?.message) {
    return new Error(anyError.message);
  }
  return new Error('内购暂未完成，请稍后重试。');
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
      console.warn('Failed to sync RevenueCat customer info:', error);
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
        throw new Error('购买完成但尚未检测到有效会员权益，请点击恢复购买或稍后重试。');
      }
      return { plan: resolvedPlan, message: '订阅已开通，会员权益已生效。' };
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
        return { plan, message: '未找到可恢复的有效订阅。' };
      }
      return { plan, message: '已恢复购买，会员权益已生效。' };
    } catch (error) {
      throw normalizePurchaseError(error);
    }
  },
};
