# Soccer Instagram Bot

Posts a picture of every soccer match happening today, with kickoff times in US
Eastern time and where to watch each competition in the USA, to an Instagram account
once a day. It runs for free on GitHub Actions.

How it works, once a day:

1. Pulls today's fixtures from [football-data.org](https://www.football-data.org/)
   (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League and more).
2. Renders them into 1080x1350 images grouped by competition, with the US broadcaster
   for each competition and kickoff times in ET (12-hour). If one image is not enough,
   it posts a carousel (up to 10 slides).
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
  bot/data/us_broadcasters.json   where to watch each competition in the USA
  bot/refresh_token.py   renews the Instagram token
  .github/workflows/daily-post.yml      daily post
  .github/workflows/refresh-token.yml   weekly token refresh
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

Long-lived tokens expire after 60 days. See "Token refresh" below to have the bot renew
it automatically.

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
| `TIME_FORMAT` | `12h` | `12h` (7:30 PM) or `24h` (19:30) |
| `TZ_LABEL` | `ET` for New York | Text after "All times"; auto for US zones, else the zone abbreviation |
| `COMPETITIONS` | all | Comma-separated codes, e.g. `PL,PD,BL1,SA,FL1,CL` |
| `IG_API_BASE` | `https://graph.facebook.com/v21.0` | Use `https://graph.instagram.com/v21.0` for Instagram Login tokens |
| `POST_WHEN_EMPTY` | `false` | Post a "no matches today" image on quiet days |
| `HASHTAGS` | `#soccer #football ...` | Caption footer |
| `IG_HANDLE` | none | Handle printed in the image footer, e.g. `@dailykickoffs` |

Competition codes: `PL` Premier League, `ELC` Championship, `PD` La Liga, `BL1`
Bundesliga, `SA` Serie A, `FL1` Ligue 1, `DED` Eredivisie, `PPL` Primeira Liga,
`CL` Champions League, `EC` Euros, `WC` World Cup, `BSA` Brasileirão, `CLI` Libertadores.

### 4. Where to watch (USA)

Each competition header shows the US English-language rights holder, taken from
`bot/data/us_broadcasters.json`. football-data.org does not provide per-match TV
listings, so this is per competition (for example every Premier League match shows
"NBC, USA Network & Peacock" rather than which of the three has that game).

Current values, checked for the 2026-27 season:

| Competition | Where to watch |
| --- | --- |
| Premier League | NBC, USA Network & Peacock |
| Championship | Paramount+ (select games on CBS) |
| La Liga | ESPN+ (select games on ESPN/ABC) |
| Bundesliga | USA Network & Fandango (free) |
| Serie A | Paramount+ & CBS Sports |
| Ligue 1 | beIN Sports |
| Eredivisie | ESPN+ |
| Primeira Liga | beIN Sports |
| Champions League | Paramount+ & CBS Sports |
| Brasileirão | Fanatiz & TV Globo Internacional |
| Copa Libertadores | beIN Sports & Fanatiz |
| World Cup | FOX & FS1 (Spanish: Telemundo & Peacock) |
| Euros | FOX & FS1 |

Rights move between networks most summers; edit the JSON file when they do. Libertadores
rights are only confirmed through the 2026 edition.

### 5. Token refresh (recommended)

`.github/workflows/refresh-token.yml` runs every Monday. If a `SECRETS_PAT` secret exists
it calls Instagram's refresh endpoint, which extends the token another 60 days, and writes
the new token back into the `IG_ACCESS_TOKEN` secret. Without `SECRETS_PAT` it opens a
reminder issue instead, since the default Actions token is not allowed to edit secrets.

To enable automatic refresh, create a fine-grained personal access token:

1. GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens >
   Generate new token.
2. Repository access: only this repository. Permissions: **Secrets: Read and write**.
   Expiration: as long as GitHub allows (you can set it to a year and renew then).
3. Save it as a repository secret named `SECRETS_PAT`.

Only tokens from "Instagram API with Instagram Login" (`IG_API_BASE` on
`graph.instagram.com`) can be refreshed this way. Facebook-login tokens need a manual
exchange with the app secret.

### 6. Schedule

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
