import type { CapacitorConfig } from "@capacitor/cli";

// The phone app shows FinSight from your computer over HTTPS on your home network,
// e.g. FINSIGHT_SERVER_URL=https://192.168.31.28:8443 (printed by `moneyos serve --phone`).
// The app trusts only FinSight's own certificate authority (see android/README.md).
const serverUrl = process.env.FINSIGHT_SERVER_URL;
if (!serverUrl || !serverUrl.startsWith("https://")) {
  throw new Error("Set FINSIGHT_SERVER_URL to the https:// address printed by `moneyos serve --phone`");
}

const config: CapacitorConfig = {
  appId: "app.finsight.phone",
  appName: "FinSight",
  webDir: "dist",
  server: { url: serverUrl, cleartext: false },
  android: { allowMixedContent: false },
};

export default config;
