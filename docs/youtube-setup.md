# YouTube upload setup (one time, about 15 minutes)

The workflow can upload the finished video straight to your channel, with title, description, tags,
the #Shorts tag, an "AI/altered content" label and an English caption track.

## 1. Create the Google API project
1. Open https://console.cloud.google.com and create a project (any name).
2. APIs & Services > Library > enable **YouTube Data API v3**.
3. APIs & Services > OAuth consent screen: User type **External**, fill the app name and your email.
   Add your own Google account under Test users.
4. APIs & Services > Credentials > Create credentials > **OAuth client ID** > type **Web application**.
   Under Authorized redirect URIs add exactly: `https://developers.google.com/oauthplayground`
5. Copy the **Client ID** and **Client secret**.

## 2. Get the refresh token
1. Open https://developers.google.com/oauthplayground
2. Gear icon (top right): tick **Use your own OAuth credentials**, paste the Client ID and secret.
3. In the left box type these two scopes and click Authorize APIs:
   `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl`
4. Sign in with the Google account that owns the channel, allow access.
5. Click **Exchange authorization code for tokens** and copy the **Refresh token**.

## 3. Add three GitHub secrets
Repository > Settings > Secrets and variables > Actions:
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`

## 4. Two traps that stop most people
- **Testing mode expires the token in 7 days.** On the OAuth consent screen click **Publish app**
  (status "In production"). Google shows an "unverified app" warning for you only; that is fine.
  Then redo step 2 so the new refresh token is long-lived.
- **Locked to private.** Videos uploaded through the API by an unverified API project are forced to
  private. Fill in Google's YouTube API Services audit form
  (https://support.google.com/youtube/contact/yt_api_form) and wait for approval. Until then you can
  upload, then switch each video to public in YouTube Studio by hand.

## 5. Use it
Actions > Generate Fractured Dimension Video > Run workflow, set **publish** to private, unlisted
or public. Optional **publish_at** (UTC, e.g. `2026-11-24T16:00:00Z`) schedules it.
Start with `private` for the first test.
Quota: each upload costs 1,600 of the 10,000 free daily units, so up to 6 uploads a day.
