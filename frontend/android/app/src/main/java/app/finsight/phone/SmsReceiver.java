package app.finsight.phone;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Hears each new SMS (with the user's permission). Long messages arrive in parts and
 * are joined first. Only transaction alerts are queued (AlertFilter); then the queue
 * is sent in the background.
 */
public class SmsReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) return;
        AlertStore store = new AlertStore(context);
        if (!store.isPaired()) return;
        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts == null) return;
        Map<String, StringBuilder> bodies = new LinkedHashMap<>();
        Map<String, Long> times = new LinkedHashMap<>();
        for (SmsMessage part : parts) {
            String sender = part.getDisplayOriginatingAddress();
            if (sender == null) continue;
            bodies.computeIfAbsent(sender, s -> new StringBuilder()).append(part.getMessageBody());
            times.putIfAbsent(sender, part.getTimestampMillis());
        }
        boolean queued = false;
        for (Map.Entry<String, StringBuilder> entry : bodies.entrySet()) {
            String body = entry.getValue().toString();
            if (AlertFilter.isTransactionAlert(entry.getKey(), body)) {
                queued |= store.enqueue(entry.getKey(), times.get(entry.getKey()), body);
            }
        }
        if (!queued) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                AlertSender.flush(context);
            } finally {
                pending.finish();
            }
        }, "finsight-sms-send").start();
    }
}
