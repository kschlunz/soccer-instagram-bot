# Soccer Instagram Bot

Posts a picture of every soccer match happening today, with kickoff times, to an
Instagram account once a day. It runs for free on GitHub Actions.

How it works, once a day:

1. Pulls today's fixtures from [football-data.org](https://www.football-data.org/)
   (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League and more).
2. Renders them into 1080x1350 images grouped by competition. If one image is not
   enough, it posts a carousel (up to 10 slides).
3. Commits the images to a `soccer-bot-images` branch so Instagram can download them
   from `raw.githubusercontent.com` (Instagram only accepts a public URL, not an upload).
4. Publishes the post through the Instagram Graph API with a caption listing every match.

```
soccer-instagram-bot/
  bot/main.py        CLI entry point
  bot/fixtures.py    football-data.org client, timezone handling, sorting
  bot/render.py      Pillow image renderer + pagination
  bot/caption.py     caption text
  bot/hosting.py     pushes images to the images branch with git plumbing
  bot/instagram.py   Graph API: containers, carousel, publish
  .github/workflows/daily-post.yml
```

## Setup

### 1. Fixtures API token (free)

Register at <https://www.football-data.org/client/register>. The free tier covers the
major European leagues, Champions League, Championship, Eredivisie, Primeira Liga,
Brasileirão and Copa Libertadores at 10 requests a minute. The bot makes one request a day.

### 2. Instagram credentials

Instagram only lets bots post to **Business or Creator** accounts.

1. In the Instagram app: Settings > Account type and tools > Switch to professional account.
2. Go to <https://developers.facebook.com/>, create an app (type "Business" or "Other"),
   and add the **Instagram** product.
3. Pick one login flow:
   - **Instagram API with Instagram Login** (simplest, no Facebook Page needed).
     Under Instagram > API setup with Instagram login, add your account as an
     Instagram tester, accept the invite in the Instagram app, then click
     *Generate token*. Set `IG_API_BASE=https://graph.instagram.com/v21.0`.
   - **Instagram API with Facebook Login.** Link the Instagram account to a Facebook
     Page, then use the Graph API Explorer to create a token with
     `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
     `pages_read_engagement`. Leave `IG_API_BASE` unset.
4. Exchange the short-lived token for a **long-lived** one (valid 60 days), for example:

   ```
   curl "https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=APP_SECRET&access_token=SHORT_TOKEN"
   ```

5. Find your Instagram user id:

   ```
   curl "https://graph.instagram.com/v21.0/me?fields=id,username&access_token=LONG_TOKEN"
   ```

Long-lived tokens expire after 60 days, so refresh it before then (a `GET
/refresh_access_token?grant_type=ig_refresh_token` call) and update the secret.

### 3. GitHub configuration

The repository must be **public** so Instagram can fetch the images from
`raw.githubusercontent.com`. For a private repo you would need another image host.

Repository **Settings > Secrets and variables > Actions**:

| Secret | Value |
| --- | --- |
| `FOOTBALL_DATA_TOKEN` | football-data.org token |
| `IG_USER_ID` | Instagram user id from step 2 |
| `IG_ACCESS_TOKEN` | long-lived Instagram token |

Optional **Variables**:

| Variable | Default | Meaning |
| --- | --- | --- |
| `TIMEZONE` | `America/New_York` | Timezone kickoff times are shown in (IANA name) |
| `COMPETITIONS` | all | Comma-separated codes, e.g. `PL,PD,BL1,SA,FL1,CL` |
| `IG_API_BASE` | `https://graph.facebook.com/v21.0` | Use `https://graph.instagram.com/v21.0` for Instagram Login tokens |
| `POST_WHEN_EMPTY` | `false` | Post a "no matches today" image on quiet days |
| `HASHTAGS` | `#soccer #football ...` | Caption footer |
| `IG_HANDLE` | none | Handle printed in the image footer, e.g. `@dailykickoffs` |

Competition codes: `PL` Premier League, `ELC` Championship, `PD` La Liga, `BL1`
Bundesliga, `SA` Serie A, `FL1` Ligue 1, `DED` Eredivisie, `PPL` Primeira Liga,
`CL` Champions League, `EC` Euros, `WC` World Cup, `BSA` Brasileirão, `CLI` Libertadores.

### 4. Schedule

`.github/workflows/daily-post.yml` runs at 11:00 UTC daily. Change the cron line to move
it. You can also run it by hand from the Actions tab: **Daily matchday post > Run
workflow**, optionally with a date or in dry-run mode (which only uploads the rendered
images as a workflow artifact so you can preview them).

## Running locally

```
git clone https://github.com/kschlunz/soccer-instagram-bot.git && cd soccer-instagram-bot
pip install -r requirements.txt
cp .env.example .env   # fill in, then export the variables (e.g. `set -a; . ./.env; set +a`)

# Preview with bundled sample data, no network or credentials needed
python -m bot.main --dry-run --sample tests/sample_matches.json --date 2026-09-05

# Preview today's real fixtures
python -m bot.main --dry-run

# Post for real
python -m bot.main

python -m pytest
```

Images and the caption land in `out/`.

## Notes and limits

- Instagram allows 100 API-published posts per account per day; this bot makes one.
- The Graph API only accepts JPEG, and aspect ratios between 4:5 and 1.91:1. The bot
  renders 1080x1350 JPEGs (4:5).
- Old images are pruned from the images branch after 30 days (`IMAGES_KEEP_DAYS`).
- `TBD` in the time column means football-data.org knows the date but the kickoff time
  is not confirmed yet. `PPD` is postponed.
