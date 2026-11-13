// Prepare the Android app on this computer: put FinSight's CA certificate into the app
// (so it trusts only your FinSight for its HTTPS connection) and sync the Capacitor project.
// Usage (PowerShell):  $env:FINSIGHT_SERVER_URL = "https://192.168.31.28:8443"; npm run phone:prepare
import { execSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ca = resolve(here, "../../data/tls/ca.pem");
const target = resolve(here, "../android/app/src/main/res/raw/finsight_ca.pem");

const url = process.env.FINSIGHT_SERVER_URL ?? "";
if (!url.startsWith("https://")) {
  console.error("Set FINSIGHT_SERVER_URL to the https:// address printed by `moneyos serve --phone`.");
  process.exit(2);
}
if (!existsSync(ca)) {
  console.error(`No ${ca}. Run \`moneyos serve --phone\` once first: it creates FinSight's certificates.`);
  process.exit(2);
}
mkdirSync(dirname(target), { recursive: true });
copyFileSync(ca, target);
console.log(`Trusting FinSight's CA from ${ca}`);
execSync("npx cap sync android", { stdio: "inherit", cwd: resolve(here, "..") });
console.log(`Ready. The app will open ${url}. Build it in Android Studio (see android/README.md).`);
