# Direct YouTube publishing (no Zapier)

`.github/workflows/youtube.yml` runs `tools/yt.py` whenever a file lands in `jobs/`.
It talks to the YouTube Data API with the channel's own OAuth token and writes `results/<id>.json`.
Free: GitHub Actions is free for public repos, YouTube API quota is 10,000 units/day.

## One-time setup (Arbaaz, ~15 min, in a browser)
1. console.cloud.google.com -> new project "offside-talk-uploader".
2. APIs & Services -> Library -> enable **YouTube Data API v3**.
3. OAuth consent screen -> External -> app name, your email -> add scope `.../auth/youtube.force-ssl` and `.../auth/youtube.upload` -> add your Google account as a test user -> then **Publish app** (In production), so the token doesn't expire after 7 days.
4. Credentials -> Create credentials -> OAuth client ID -> **Web application** -> Authorized redirect URI `https://developers.google.com/oauthplayground` -> copy Client ID + Client secret.
5. developers.google.com/oauthplayground -> gear icon -> "Use your own OAuth credentials" -> paste both.
   In "Input your own scopes" type: `https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube.upload` -> Authorize APIs -> sign in with the account that owns Offside Talk (pick the channel) -> Allow (click "Advanced -> go to app" on the unverified warning) -> "Exchange authorization code for tokens" -> copy the **Refresh token**.
6. GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret, three times:
   `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
7. Apply for the YouTube API audit (free): support.google.com/youtube/contact/yt_api_form ("YouTube API Services - Audit and Quota Extension Form"). Until the project passes, Google keeps API uploads **private**. The autopilot detects that and tells you; you can flip them to Public in YouTube Studio meanwhile.

## Job format
See the docstring in `tools/yt.py`.
