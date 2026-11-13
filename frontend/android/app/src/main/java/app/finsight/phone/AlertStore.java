package app.finsight.phone;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Pairing details and the queue of alerts not sent yet, in app-private storage
 * (excluded from backups: allowBackup is off). Each message gets a fingerprint so it
 * is sent once, even if Android delivers it twice or the history is imported again.
 */
public final class AlertStore {
    private static final String PREFS = "finsight_sms";
    private static final int REMEMBER_SENT = 5000;
    private final SharedPreferences prefs;

    public AlertStore(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public synchronized void pair(String serverUrl, String key) {
        prefs.edit().putString("server", serverUrl).putString("key", key).apply();
    }

    public synchronized void unpair() {
        prefs.edit().remove("server").remove("key").remove("queue").apply();
    }

    public synchronized boolean isPaired() {
        return prefs.getString("key", null) != null && prefs.getString("server", null) != null;
    }

    public synchronized String server() { return prefs.getString("server", null); }

    public synchronized String key() { return prefs.getString("key", null); }

    public synchronized String lastSentAt() { return prefs.getString("lastSentAt", null); }

    public synchronized void markSent(JSONArray alerts, String when) {
        Set<String> sent = sentSet();
        for (int i = 0; i < alerts.length(); i++) {
            sent.add(alerts.optJSONObject(i).optString("fingerprint"));
        }
        while (sent.size() > REMEMBER_SENT) sent.remove(sent.iterator().next());
        prefs.edit().putString("sent", new JSONArray(sent).toString()).putString("lastSentAt", when).apply();
    }

    /** Queue an alert unless it was queued or sent before. Returns true if it is new. */
    public synchronized boolean enqueue(String sender, long timestampMs, String body) {
        String fingerprint = fingerprint(sender, timestampMs, body);
        if (sentSet().contains(fingerprint)) return false;
        JSONArray queue = queue();
        for (int i = 0; i < queue.length(); i++) {
            if (fingerprint.equals(queue.optJSONObject(i).optString("fingerprint"))) return false;
        }
        try {
            queue.put(new JSONObject().put("sender", sender).put("timestamp_ms", timestampMs)
                    .put("body", body.length() > 2000 ? body.substring(0, 2000) : body)
                    .put("fingerprint", fingerprint));
        } catch (JSONException e) {
            return false;
        }
        prefs.edit().putString("queue", queue.toString()).apply();
        return true;
    }

    public synchronized JSONArray queue() {
        try {
            return new JSONArray(prefs.getString("queue", "[]"));
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    public synchronized void clearQueue(int count) {
        JSONArray queue = queue();
        JSONArray rest = new JSONArray();
        for (int i = count; i < queue.length(); i++) rest.put(queue.opt(i));
        prefs.edit().putString("queue", rest.toString()).apply();
    }

    private Set<String> sentSet() {
        Set<String> out = new LinkedHashSet<>();
        try {
            JSONArray array = new JSONArray(prefs.getString("sent", "[]"));
            for (int i = 0; i < array.length(); i++) out.add(array.getString(i));
        } catch (JSONException ignored) {
            // start afresh; the server also drops repeats
        }
        return out;
    }

    static String fingerprint(String sender, long timestampMs, String body) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest((sender + "\n" + timestampMs + "\n" + body).getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (int i = 0; i < 12; i++) hex.append(String.format("%02x", hash[i]));
            return hex.toString();
        } catch (Exception e) {
            return sender + timestampMs;
        }
    }
}
