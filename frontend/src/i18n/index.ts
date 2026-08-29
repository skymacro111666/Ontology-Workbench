import i18next from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import zh from './locales/zh.json'

const isTest = import.meta.env.MODE === 'test'

void i18next
  .use(initReactI18next)
  .use(LanguageDetector)
  .init({
    // Tests pin zh: jsdom's navigator is en-US while every existing string
    // assertion is Chinese. Production goes through the detector instead
    // (localStorage ow_lang → navigator).
    lng: isTest ? 'zh' : undefined,
    fallbackLng: 'zh',
    supportedLngs: ['zh', 'en'],
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'ow_lang',
    },
    interpolation: { escapeValue: false }, // React already escapes
    resources: { zh: { translation: zh }, en: { translation: en } },
  })

export default i18next
