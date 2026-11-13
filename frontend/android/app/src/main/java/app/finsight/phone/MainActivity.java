package app.finsight.phone;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(FinSightSmsPlugin.class); // before super.onCreate, so the page can use it
        super.onCreate(savedInstanceState);
    }
}
