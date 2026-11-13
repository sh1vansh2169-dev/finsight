// The bridge to the FinSight phone app's native SMS code. It exists only inside the
// Android app (Capacitor injects window.Capacitor); in a browser everything here is absent.

export interface SmsStatus {
  paired: boolean;
  permission: "granted" | "denied" | "prompt";
  queued: number; // alerts waiting to be sent (e.g. away from home Wi-Fi)
  lastSentAt: string | null;
}

export interface FinSightSms {
  status(): Promise<SmsStatus>;
  requestPermission(): Promise<{ permission: SmsStatus["permission"] }>;
  pair(options: { serverUrl: string; key: string }): Promise<void>;
  unpair(): Promise<void>;
  importHistory(options: { days: number }): Promise<{ found: number; sent: number }>;
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean;
  Plugins?: { FinSightSms?: FinSightSms };
}

function capacitor(): CapacitorGlobal | undefined {
  return (window as unknown as { Capacitor?: CapacitorGlobal }).Capacitor;
}

export function nativeSms(): FinSightSms | null {
  const cap = capacitor();
  return cap?.isNativePlatform?.() && cap.Plugins?.FinSightSms ? cap.Plugins.FinSightSms : null;
}
