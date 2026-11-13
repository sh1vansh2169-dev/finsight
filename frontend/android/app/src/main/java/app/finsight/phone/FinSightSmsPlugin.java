package app.finsight.phone;

import android.Manifest;
import android.database.Cursor;
import android.net.Uri;
import android.provider.Telephony;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The bridge FinSight's web page uses inside the app (see frontend/src/lib/native.ts):
 * status, requestPermission, pair, unpair, importHistory.
 */
@CapacitorPlugin(
        name = "FinSightSms",
        permissions = {
                @Permission(strings = {Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS}, alias = "sms")
        })
public class FinSightSmsPlugin extends Plugin {
    private final ExecutorService background = Executors.newSingleThreadExecutor();

    @Override
    public void load() {
        background.execute(() -> AlertSender.flush(getContext())); // send anything queued while away
    }

    private String permission() {
        PermissionState state = getPermissionState("sms");
        if (state == PermissionState.GRANTED) return "granted";
        if (state == PermissionState.DENIED) return "denied";
        return "prompt";
    }

    @PluginMethod
    public void status(PluginCall call) {
        AlertStore store = new AlertStore(getContext());
        JSObject out = new JSObject();
        out.put("paired", store.isPaired());
        out.put("permission", permission());
        out.put("queued", store.queue().length());
        out.put("lastSentAt", store.lastSentAt());
        call.resolve(out);
    }

    @PluginMethod
    public void requestPermission(PluginCall call) {
        if (getPermissionState("sms") == PermissionState.GRANTED) {
            resolvePermission(call);
        } else {
            requestPermissionForAlias("sms", call, "afterPermission");
        }
    }

    @PermissionCallback
    private void afterPermission(PluginCall call) {
        resolvePermission(call);
    }

    private void resolvePermission(PluginCall call) {
        JSObject out = new JSObject();
        out.put("permission", permission());
        call.resolve(out);
    }

    @PluginMethod
    public void pair(PluginCall call) {
        String server = call.getString("serverUrl");
        String key = call.getString("key");
        if (server == null || !server.startsWith("https://") || key == null || key.length() < 10) {
            call.reject("FinSight must be opened over https:// to connect this phone");
            return;
        }
        new AlertStore(getContext()).pair(server, key);
        call.resolve();
    }

    @PluginMethod
    public void unpair(PluginCall call) {
        new AlertStore(getContext()).unpair();
        call.resolve();
    }

    /** Queue transaction alerts already in the inbox (last N days), then send them. */
    @PluginMethod
    public void importHistory(PluginCall call) {
        if (getPermissionState("sms") != PermissionState.GRANTED) {
            call.reject("SMS permission is needed first");
            return;
        }
        int days = Math.max(1, Math.min(365, call.getInt("days", 90)));
        background.execute(() -> {
            AlertStore store = new AlertStore(getContext());
            long since = System.currentTimeMillis() - days * 24L * 60 * 60 * 1000;
            int found = 0;
            Uri inbox = Telephony.Sms.Inbox.CONTENT_URI;
            String[] columns = {Telephony.Sms.ADDRESS, Telephony.Sms.DATE, Telephony.Sms.BODY};
            try (Cursor cursor = getContext().getContentResolver().query(
                    inbox, columns, Telephony.Sms.DATE + " >= ?", new String[]{String.valueOf(since)},
                    Telephony.Sms.DATE + " ASC")) {
                while (cursor != null && cursor.moveToNext()) {
                    String sender = cursor.getString(0);
                    long when = cursor.getLong(1);
                    String body = cursor.getString(2);
                    if (AlertFilter.isTransactionAlert(sender, body)) {
                        found++;
                        store.enqueue(sender, when, body);
                    }
                }
            } catch (Exception e) {
                call.reject("Could not read SMS: " + e.getMessage());
                return;
            }
            int sent = AlertSender.flush(getContext());
            JSObject out = new JSObject();
            out.put("found", found);
            out.put("sent", sent);
            call.resolve(out);
        });
    }
}
