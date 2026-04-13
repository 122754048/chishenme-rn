# ChiShenMe/Teller — 全面修复计划

## Phase 1: P0 严重问题修复

### 1.1 修复依赖缺失
```bash
npx expo install expo-image-picker expo-location expo-dev-client react-native-purchases
```
确保 `npx tsc --noEmit` 零错误。

### 1.2 品牌名称统一为 Teller
- `package.json`: name → `teller-rn`
- `src/storage/index.ts`: 所有 AsyncStorage key 前缀从 `@chishenme/` → `@teller/`
  - **必须写迁移逻辑**：启动时检查旧 key，如果有值就迁移到新 key，然后删除旧 key
- `src/components/OnboardingGuide.tsx`: GUIDE_KEY 从 `@chishenme/has_seen_guide` → `@teller/has_seen_guide`（也需迁移）

### 1.3 StatusBar 深色模式适配
- `App.tsx`: `<StatusBar style="dark" />` → `<StatusBar style={isDark ? 'light' : 'dark'} />`
- 需要从 theme 获取 isDark 状态。注意 StatusBar 在 AppProvider 内部，可使用 useColorScheme

### 1.4 安全：.env.example + .gitignore
- 创建 `.env.example` 列出所有 EXPO_PUBLIC_* 和后端环境变量
- 确认 `.gitignore` 包含 `.env`、`.env.local`

## Phase 2: P1 重要问题修复

### 2.1 深色模式硬编码颜色修复
在以下文件中，将硬编码的浅色 rgba 值替换为 theme token：
- `src/screens/Detail.tsx`: actionBar backgroundColor
- `src/screens/Checkout.tsx`: footer backgroundColor  
- `src/screens/Upgrade.tsx`: footer backgroundColor

统一模式：
```ts
backgroundColor: isDark ? 'rgba(20,18,17,0.98)' : 'rgba(255,253,252,0.98)'
```
或更好的方案：直接用 `t.colors.surface` + opacity

### 2.2 useThemedStyles 性能优化
`src/theme/useTheme.ts`:
```ts
export function useThemedStyles<T extends StyleSheet.NamedStyles<T>>(
  factory: (theme: AppTheme) => T,
): T {
  const colorScheme = useColorScheme();
  const theme = colorScheme === 'dark' ? darkTheme : lightTheme;
  return useMemo(() => StyleSheet.create(factory(theme)), [colorScheme]);
}
```
注意：依赖项是 `colorScheme` 而非 `theme`，因为 theme 对象在同一 colorScheme 下不变。
需要 import useMemo from react。

### 2.3 创建 .env.example
```
# Frontend (Expo)
EXPO_PUBLIC_API_BASE_URL=
EXPO_PUBLIC_BACKEND_BOOTSTRAP_PASSWORD=
EXPO_PUBLIC_RC_IOS_API_KEY=
EXPO_PUBLIC_RC_ENTITLEMENT_ID=premium
EXPO_PUBLIC_RC_PRO_PRODUCT_ID=teller.pro.monthly
EXPO_PUBLIC_RC_FAMILY_PRODUCT_ID=teller.family.monthly
EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS=false

# Backend
APP_ENV=dev
JWT_SECRET=
DB_PATH=
ALIPAY_APP_ID=
ALIPAY_PUBLIC_KEY=
REVENUECAT_WEBHOOK_SECRET=
REVENUECAT_ENTITLEMENT_ID=premium
REVENUECAT_PRO_PRODUCT_ID=teller.pro.monthly
REVENUECAT_FAMILY_PRODUCT_ID=teller.family.monthly
GOOGLE_PLACES_API_KEY=
OPENAI_API_KEY=
```

### 2.4 后端 RevenueCat 产品 ID 默认值对齐
`backend/app/config.py`:
- `revenuecat_pro_product_id` 默认值 → `teller.pro.monthly`
- `revenuecat_family_product_id` 默认值 → `teller.family.monthly`

### 2.5 移除 Android 多余 RECORD_AUDIO 权限
`app.json` → android.permissions: 删除 `android.permission.RECORD_AUDIO`

## Phase 3: 验证

### 3.1 TypeScript 编译
```bash
npx tsc --noEmit
```
目标：零错误

### 3.2 Lint
```bash
npm run lint
```

### 3.3 Test
```bash
npm test
```
