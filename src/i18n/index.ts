/**
 * i18n bootstrap.
 *
 * - Default language: English (project is going-to-market English-first)
 * - Supported: en, zh, es, ja (es/ja stubs ship in v1 to validate price localization)
 * - Storage: AsyncStorage so user's choice persists across sessions
 * - Pluralization & ICU MessageFormat handled by i18next core
 *
 * Usage:
 *   const { t } = useTranslation();
 *   t('home.title')                           // "Find a better pick, faster."
 *   t('home.quotaRemaining', { count: 2 })    // "2 picks left today" (with plural)
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import * as Localization from 'expo-localization';
import AsyncStorage from '@react-native-async-storage/async-storage';

import en from './locales/en.json';
import zh from './locales/zh.json';
import es from './locales/es.json';
import ja from './locales/ja.json';

const LANGUAGE_STORAGE_KEY = '@teller/language';

export const SUPPORTED_LANGUAGES = ['en', 'zh', 'es', 'ja'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

/**
 * Pick best language from device locale, falling back to English.
 * Logic: device list -> first match against SUPPORTED_LANGUAGES -> 'en'
 */
function detectDeviceLanguage(): SupportedLanguage {
  try {
    const locales = Localization.getLocales();
    for (const locale of locales) {
      const code = locale.languageCode?.toLowerCase();
      if (code && (SUPPORTED_LANGUAGES as readonly string[]).includes(code)) {
        return code as SupportedLanguage;
      }
    }
  } catch {
    // Localization API can fail on some sandbox/jest environments
  }
  return 'en';
}

let initialized = false;

export async function initI18n(): Promise<void> {
  if (initialized) return;
  initialized = true;

  let lang: SupportedLanguage;
  try {
    const saved = await AsyncStorage.getItem(LANGUAGE_STORAGE_KEY);
    lang =
      saved && (SUPPORTED_LANGUAGES as readonly string[]).includes(saved)
        ? (saved as SupportedLanguage)
        : detectDeviceLanguage();
  } catch {
    lang = detectDeviceLanguage();
  }

  await i18n.use(initReactI18next).init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
      es: { translation: es },
      ja: { translation: ja },
    },
    lng: lang,
    fallbackLng: 'en',
    interpolation: { escapeValue: false }, // React already escapes
    returnNull: false,
    compatibilityJSON: 'v4',
  });
}

export async function setLanguage(lang: SupportedLanguage): Promise<void> {
  await i18n.changeLanguage(lang);
  try {
    await AsyncStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  } catch {
    // Non-fatal — change still applied in-memory
  }
}

export function getCurrentLanguage(): SupportedLanguage {
  const lng = i18n.language?.split('-')[0];
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(lng)
    ? (lng as SupportedLanguage)
    : 'en';
}

export default i18n;
