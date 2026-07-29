import '@fontsource/noto-sans/400.css';
import '@fontsource/noto-sans/600.css';
import '@fontsource/noto-sans-sc/400.css';
import '@fontsource/noto-sans-sc/600.css';
import '@fontsource/noto-sans-arabic/400.css';
import '@fontsource/noto-sans-arabic/600.css';

const ARABIC = /[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]/;
const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;

export const fontFamilyForText = (text: string): string => {
  if (ARABIC.test(text)) {
    return 'Noto Sans Arabic';
  }
  if (CJK.test(text)) {
    return 'Noto Sans SC';
  }
  return 'Noto Sans';
};

export const directionForText = (text: string): 'ltr' | 'rtl' =>
  ARABIC.test(text) ? 'rtl' : 'ltr';
