package app.finsight.phone;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** The same cases as the server's tests (backend/tests/domain/test_sms.py). Run: gradlew test */
public class AlertFilterTest {
    @Test
    public void bankAlertsAreSent() {
        assertTrue(AlertFilter.isTransactionAlert("AX-HDFCBK",
                "Sent Rs.500.00 From HDFC Bank A/C *1234 To SWIGGY On 12/03/26 Ref 412345678901"));
        assertTrue(AlertFilter.isTransactionAlert("JD-SBIUPI",
                "Dear UPI user A/C X1234 debited by Rs 250.0 on date 12Mar26 trf to RAVI KUMAR Refno 412398765432"));
        assertTrue(AlertFilter.isTransactionAlert("BZ-AXISBK",
                "INR 999.00 spent on Axis Bank Card XX9876 at NETFLIX on 14-03-26."));
    }

    @Test
    public void aSafetyFooterDoesNotHideARealAlert() {
        assertTrue(AlertFilter.isTransactionAlert("AX-HDFCBK",
                "Sent Rs.500.00 To SWIGGY Ref 412345678901. Never share your OTP/PIN with anyone."));
    }

    @Test
    public void otpsNeverLeaveThePhone() {
        assertFalse(AlertFilter.isTransactionAlert("AX-HDFCBK",
                "Your OTP for transaction of Rs.5000 at AMAZON is 482913. Do not share."));
        assertFalse(AlertFilter.isTransactionAlert("AX-HDFCBK",
                "482913 is your OTP for a transaction of Rs.5000 debited at AMAZON."));
        assertFalse(AlertFilter.isTransactionAlert("AX-HDFCBK",
                "One time password for Rs 999 spent at NETFLIX is 551288"));
    }

    @Test
    public void personalMessagesNeverLeaveThePhone() {
        assertFalse(AlertFilter.isTransactionAlert("+919800000000", "I paid Rs.400 for the cab, send me half"));
        assertFalse(AlertFilter.isTransactionAlert("9800000000", "Sent you Rs 200 on GPay"));
    }

    @Test
    public void messagesWithoutMoneyMovementAreIgnored() {
        assertFalse(AlertFilter.isTransactionAlert("AX-HDFCBK", "Your A/c XX1234 Avl Bal is Rs.12,000.50"));
        assertFalse(AlertFilter.isTransactionAlert("AX-HDFCBK", "Your card statement is ready"));
    }
}
