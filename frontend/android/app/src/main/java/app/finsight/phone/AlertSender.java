package app.finsight.phone;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

import javax.net.ssl.HttpsURLConnection;

/**
 * Sends queued alerts to FinSight over HTTPS. Trust comes from the app's network
 * security config, which accepts only FinSight's own certificate authority for
 * this connection. Runs off the main thread; failures leave alerts queued.
 */
public final class AlertSender {
    private static final int BATCH = 200;
    private AlertSender() {}

    /** Send everything queued. Returns how many were sent (0 if FinSight is unreachable). */
    public static synchronized int flush(Context context) {
        AlertStore store = new AlertStore(context);
        if (!store.isPaired()) return 0;
        int sent = 0;
        while (true) {
            JSONArray queue = store.queue();
            if (queue.length() == 0) return sent;
            JSONArray batch = new JSONArray();
            for (int i = 0; i < Math.min(BATCH, queue.length()); i++) {
                JSONObject alert = queue.optJSONObject(i);
                try {
                    batch.put(new JSONObject().put("sender", alert.getString("sender"))
                            .put("timestamp_ms", alert.getLong("timestamp_ms")).put("body", alert.getString("body")));
                } catch (Exception ignored) {
                    // a damaged entry is skipped
                }
            }
            if (!post(store, batch)) return sent;
            JSONArray done = new JSONArray();
            for (int i = 0; i < Math.min(BATCH, queue.length()); i++) done.put(queue.opt(i));
            store.markSent(done, now());
            store.clearQueue(done.length());
            sent += done.length();
        }
    }

    private static boolean post(AlertStore store, JSONArray alerts) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(store.server() + "/api/v1/phone/alerts");
            connection = (HttpURLConnection) url.openConnection();
            if (!(connection instanceof HttpsURLConnection)) return false; // never send over plain HTTP
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(20000);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("X-FinSight-Device", store.key());
            byte[] body = new JSONObject().put("alerts", alerts).toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream out = connection.getOutputStream()) {
                out.write(body);
            }
            int code = connection.getResponseCode();
            if (code == 401) store.unpair(); // disconnected in FinSight: stop sending
            return code == 200;
        } catch (Exception e) {
            return false; // not on home Wi-Fi, FinSight not running, ...: try again later
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static String now() {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date());
    }
}
