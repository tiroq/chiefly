export function getTelegramWebApp() {
  return window.Telegram?.WebApp;
}

export function hapticImpact(style: "light" | "medium" | "heavy" | "rigid" | "soft" = "medium") {
  getTelegramWebApp()?.HapticFeedback?.impactOccurred(style);
}

export function hapticNotification(type: "error" | "success" | "warning") {
  getTelegramWebApp()?.HapticFeedback?.notificationOccurred(type);
}

export function hapticSelection() {
  getTelegramWebApp()?.HapticFeedback?.selectionChanged();
}

export function closeApp() {
  getTelegramWebApp()?.close();
}

export function expandApp() {
  getTelegramWebApp()?.expand();
}

export function isInTelegram(): boolean {
  return !!getTelegramWebApp()?.initData;
}
