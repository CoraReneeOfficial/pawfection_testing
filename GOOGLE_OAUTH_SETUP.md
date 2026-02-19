# Google OAuth Configuration

To fix the "Redirect URI mismatch" error and ensure seamless Google integration for both your testing and production domains, you need to add the following URLs to your Google Cloud Console.

## Steps

1.  Go to the **[Google Cloud Console](https://console.cloud.google.com/)**.
2.  Select your project.
3.  Navigate to **APIs & Services** > **Credentials**.
4.  Click on the **OAuth 2.0 Client ID** you are using for this application.
5.  Under the **Authorized redirect URIs** section, click **ADD URI**.
6.  Add **ALL** of the following URLs (copy and paste them exactly):

### Current Testing Domain
*   `https://pawfectiontesting.up.railway.app/google/store_callback`
*   `https://pawfectiontesting.up.railway.app/google/callback`

### Future Production Domain
*   `https://pawfection.grooming.solutions.up.railway.app/google/store_callback`
*   `https://pawfection.grooming.solutions.up.railway.app/google/callback`

7.  Click **SAVE**.

## Verification

After saving, you can verify that the application is detecting the correct URL by visiting the following page on your deployed app:

`https://pawfectiontesting.up.railway.app/google/debug-redirect-uri`

This page will show you the exact Redirect URIs the application is generating. Ensure they match what you entered in the Google Cloud Console.
