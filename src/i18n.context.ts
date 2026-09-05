import { createContext } from "react";
import type { Locale, Translate } from "./i18n";

export interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translate;
}

// Keep identity stable when translations/components are hot-reloaded in development.
export const I18nContext = createContext<I18nValue | undefined>(undefined);
