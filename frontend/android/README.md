# FinSight phone app (Android)

FinSight inside an app: the same screens, opened from your computer over
HTTPS on your home Wi-Fi, plus the one thing a website cannot do: with your
permission, it reads new **bank and UPI SMS alerts** and sends them to
FinSight, where they wait under Transactions for your review.

What it sends, and what it never sends:

- Only messages from bank-style senders (like `AX-HDFCBK`) that mention money
  moving (`AlertFilter.java`). FinSight's server checks them again.
- Never OTPs, never messages from people, never anything else.
- The phone's key can only send alerts: it cannot read your data or sign in.
  Disconnect the phone in FinSight (Profile → Phone app) and the key stops working.

## Build it (once)

Needs Android Studio (free): https://developer.android.com/studio

1. On your computer, start FinSight for the phone:
   `.\.venv\Scripts\moneyos.exe serve --phone` (from the repo root).
   It prints an address like `https://192.168.31.28:8443` and creates FinSight's
   certificates in `data\tls`. Windows may ask to allow it on private networks: allow.
2. Prepare the app with that address:
   ```powershell
   cd frontend
   $env:FINSIGHT_SERVER_URL = "https://192.168.31.28:8443"
   npm run phone:prepare
   ```
3. Open `frontend\android` in Android Studio, let it finish syncing, then
   **Build → Build App Bundle(s) / APK(s) → Build APK(s)**. The APK is in
   `app\build\outputs\apk\debug\`. (Or `.\gradlew assembleDebug` in this folder.)
4. Copy the APK to your phone and open it. Android asks to allow installing
   from that source: allow it once.

Tests for the phone's filter: `.\gradlew test` (same cases as the server's).

## Use it

1. Open FinSight on the phone (on home Wi-Fi, with `serve --phone` running) and sign in.
2. Profile → Phone app → **Connect this phone**. Android asks for SMS permission.
3. Optional: **Bring in the last 90 days**.

New alerts are sent as they arrive. Away from home Wi-Fi, they wait on the
phone and go the next time FinSight is reachable (when the app opens, or with
the next alert).

If your computer's Wi-Fi address changes, FinSight renews its certificate by
itself, but the app still opens the old address: run step 2 with the new
address and rebuild.
