package app.finsight.phone;

import java.util.regex.Pattern;

/**
 * Decides, ON THE PHONE, which messages may be sent to FinSight: only messages that
 * look like bank or UPI transaction alerts. OTPs and personal messages never leave the
 * phone. FinSight's server applies its own, stricter rules again (domain/sms.py).
 */
public final class AlertFilter {
    private AlertFilter() {}

    // Indian business senders look like "AX-HDFCBK" or "VM-ICICIT-S"; people have phone numbers.
    private static final Pattern BUSINESS_SENDER = Pattern.compile("^[A-Za-z]{2}-[A-Za-z0-9]{3,9}(-[A-Za-z])?$|^[A-Za-z][A-Za-z0-9]{3,10}$");
    private static final Pattern MONEY = Pattern.compile("(?i)(\\b(rs|inr)(?=[\\s.\\d])|₹)");
    private static final Pattern MOVEMENT = Pattern.compile(
            "(?i)\\b(debited|credited|spent|paid|sent|received|withdrawn|deposited|refunded|transferred)\\b");
    // An OTP message has a code next to the OTP words. Real alerts often end with "never share
    // your OTP/PIN": that footer alone must not hide a payment. Same rule as the server (domain/sms.py).
    private static final String OTP_WORDS = "(?:\\botp\\b|one[- ]time password|verification code)";
    private static final Pattern NEVER = Pattern.compile(
            "(?i)" + OTP_WORDS + "[^\\n]{0,60}?(?:\\bis\\b|:|-)\\s*\\d{4,8}\\b"
                    + "|\\b\\d{4,8}\\s+is\\s+(?:your|the)\\s+" + OTP_WORDS
                    + "|verification code\\s*:?\\s*\\d{4,8}\\b");

    public static boolean isTransactionAlert(String sender, String body) {
        if (sender == null || body == null) return false;
        String s = sender.trim();
        if (!BUSINESS_SENDER.matcher(s).matches()) return false;
        if (NEVER.matcher(body).find()) return false;
        return MONEY.matcher(body).find() && MOVEMENT.matcher(body).find();
    }
}
