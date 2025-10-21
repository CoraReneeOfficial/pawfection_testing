# Railway Deployment Guide for Pawfection

This guide will help you deploy your Pawfection app to Railway with PostgreSQL and persistent storage.

## Prerequisites

1. A Railway account (https://railway.app)
2. Git repository connected to Railway
3. PostgreSQL database provisioned on Railway

## Step 1: Set Up Railway Project

1. Log in to Railway
2. Create a new project
3. Connect your GitHub repository
4. Add a PostgreSQL database to your project

## Step 2: Configure Environment Variables

In your Railway project settings, add the following environment variables:

### Required Variables:

```
FLASK_SECRET_KEY=<generate-a-secure-random-key>
FLASK_ENV=production
FLASK_DEBUG=0
PERSISTENT_DATA_DIR=/persistent_storage
```

### Database:
Railway will automatically set `DATABASE_URL` when you add PostgreSQL

### Google OAuth (if using):
```
GOOGLE_CLIENT_ID=<your-google-client-id>
GOOGLE_CLIENT_SECRET=<your-google-client-secret>
```

### Stripe (if using):
```
STRIPE_PUBLISHABLE_KEY=<your-stripe-publishable-key>
STRIPE_SECRET_KEY=<your-stripe-secret-key>
STRIPE_PRICE_ID=<your-stripe-price-id>
STRIPE_WEBHOOK_SECRET=<your-stripe-webhook-secret>
```

## Step 3: Set Up Persistent Storage

1. In Railway, go to your project settings
2. Navigate to Volumes
3. Create a new volume
4. Mount it at `/persistent_storage`
5. This will store your uploads, Google tokens, and notification settings

## Step 4: Deploy

1. Push your code to GitHub
2. Railway will automatically detect the changes and deploy
3. The build process will:
   - Install dependencies from `requirements.txt`
   - Run database migrations
   - Start the app with gunicorn

## Step 5: Initialize Database

After first deployment:

1. Open Railway Shell for your service
2. Run migrations:
   ```bash
   python -m flask db upgrade
   ```

## Step 6: Access Your App

Your app will be available at the Railway-provided URL (e.g., `https://your-app.railway.app`)

## Important Notes

### Database
- The app automatically uses PostgreSQL when `DATABASE_URL` is set
- Falls back to SQLite for local development
- PostgreSQL URL format is automatically fixed (postgres:// → postgresql://)

### File Uploads
- All uploads are stored in `/persistent_storage/uploads`
- Ensure the volume is properly mounted

### Security
- `.env` file is excluded from git via `.gitignore`
- HTTPS cookies are enabled in production
- All sensitive data should be in environment variables

### Migrations
- Run `flask db migrate` locally when you change models
- Commit the migration files to git
- Railway will run `flask db upgrade` automatically

## Troubleshooting

### Database Connection Issues
- Verify `DATABASE_URL` is set correctly
- Check PostgreSQL service is running

### File Upload Errors
- Verify `/persistent_storage` volume is mounted
- Check write permissions

### Migration Errors
- Try running migrations manually in Railway shell
- Check migration files in `migrations/versions/`

### Environment Variables
- Double-check all required variables are set
- Restart the service after changing variables

## Local Development

For local development:

1. Create a `.env` file (never commit this!)
2. Set `FLASK_ENV=development`
3. Run with `python app.py`
4. Database will use SQLite by default

## Support

For issues, check:
- Railway logs in the dashboard
- App logs via Railway CLI: `railway logs`
- Database logs in PostgreSQL service
