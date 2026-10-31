// MAX Bridge: подписанная строка initData передаётся бэкенду, а не initDataUnsafe.
export function getWebApp() {
  return window.WebApp || window.MaxApp || null;
}

export function getInitData() {
  const raw = getWebApp()?.initData;
  return typeof raw === "string" ? raw : "";
}

export function signalReady() {
  const app = getWebApp();
  app?.ready?.();
  app?.expand?.();
}
