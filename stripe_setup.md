# Setting up Stripe Connect for Checkout

To ensure the checkout flow can process real credit card payments via Stripe Connect on behalf of your tenant stores (groomers), follow these steps to properly set up and connect your platform account.

## 1. Stripe Account Configuration

1. **Sign in to the Stripe Dashboard** as the platform owner.
2. Ensure you have **Stripe Connect** enabled for your account. You can configure this in your Stripe Dashboard under the **Connect** section.
3. Retrieve your **API Keys** from the *Developers > API keys* section:
   - Publishable Key (`pk_test_...` or `pk_live_...`)
   - Secret Key (`sk_test_...` or `sk_live_...`)
4. Set these in your environment variables on Railway/Heroku/local:
   ```bash
   STRIPE_PUBLISHABLE_KEY=pk_...
   STRIPE_SECRET_KEY=sk_...
   ```

## 2. Onboarding Connected Accounts

The `Store` model now includes a `stripe_account_id` column. This represents the Connected Account ID (`acct_...`) of the groomer/tenant.

**You must populate this field for a store to accept card payments via Stripe Elements.**

### How to get the `stripe_account_id`:
1. In your Stripe Dashboard, go to **Connect > Accounts**.
2. Click **Create** to create an account for your tenant (Standard, Express, or Custom).
3. After the account is created and onboarding is complete, copy the **Account ID** (it starts with `acct_`).
4. Update the tenant's `Store` record in your database with this ID:
   ```sql
   UPDATE store SET stripe_account_id = 'acct_123456789' WHERE id = [STORE_ID];
   ```

*(In the future, you can build an automated onboarding route utilizing `stripe.AccountLink.create` to automatically populate this field when a groomer clicks "Connect with Stripe" in their settings).*

## 3. Testing the Checkout Flow

1. Create a test appointment.
2. In the POS Checkout, select the appointment and click the **Checkout Now** button.
3. Confirm the services and enter a tip.
4. On the Payment Selection screen, select **Card**.
   - *If the store has a `stripe_account_id` in the database, the purple Stripe Elements widget will load.*
   - *If the store does not have a connected account ID, the widget will fail to load with a secure payment error.*
5. Use a Stripe Test Card (e.g., `4242 4242 4242 4242`) to process a payment.
6. Once completed, the receipt will automatically document the split payment(s) and any cash tip separated from the card charge.
