"""
Agent 10 -- Publisher

Role: take Agent 9's SEO package + Agent 8's finished video, upload it
to YouTube as UNLISTED for manual review. Does NOT flip it to public --
that's a deliberate separate step (see conversation log: "private/
unlisted review then live" was the explicit decision for this pipeline,
given nothing upstream guarantees zero factual errors or a clean render
every single time -- ISSUE-19/23's silent CTA loss is a real, currently
open example of a defect that could otherwise ship live unattended).

OAuth2 setup (one-time, done in Google Cloud Console before this file
can run at all):
  1. GCP project created, YouTube Data API v3 enabled
  2. Google Auth Platform configured: Branding, Audience (External,
     your own email added as a test user), Data Access (scope:
     .../auth/youtube.upload)
  3. OAuth Client ID created as "Desktop app" type -> downloaded as
     client_secrets.json

Why "Desktop app" flow (InstalledAppFlow), not a web-server flow:
  this is a local script run from a terminal, not a deployed web app --
  InstalledAppFlow opens a local browser window for one-time consent,
  then caches a reusable token to disk. No public redirect URI needed.

Path resolution -- the actual bug found on first real test:
  client_secrets.json genuinely existed on disk (project root), but a
  bare relative path ("client_secrets.json") silently resolved against
  whatever the CURRENT WORKING DIRECTORY happened to be when Jupyter's
  kernel started -- NOT necessarily the project root, and NOT
  necessarily this file's own directory. Same root cause, same fix
  pattern as agent6_1.py's _find_venv_python(): _find_project_file()
  below checks several real candidate locations rather than trusting
  one guessed relative path.

Token caching: youtube_token.json is created on first successful auth
  and reused on every subsequent run -- you should NOT need to re-open
  a browser every single pipeline run. Real caveat: apps in OAuth
  "Testing" status get refresh tokens that expire after 7 days -- if
  this file goes stale, the next run reopens a browser for one-time
  re-consent rather than failing silently.

Quota cost (YouTube Data API v3, default 10,000 units/day):
  videos.insert (the upload itself): 1,600 units
  thumbnails.set (custom thumbnail, separate required call): 50 units
  Total per video: 1,650 units -> supports ~6 videos/day on default
  quota, comfortably above this project's 2/day target.

Rerun protection: before uploading, checks a persistent local log
  (published_videos.json, saved alongside client_secrets.json) keyed
  by video_path -- prevents accidentally re-uploading the same video
  if a checkpoint gets re-run during testing.
"""

import os
import json
import time
import subprocess

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILENAME = "client_secrets.json"
TOKEN_FILENAME = "youtube_token.json"
PUBLISHED_LOG_FILENAME = "published_videos.json"

PRIVACY_STATUS = "unlisted"  # deliberate -- see module docstring

RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
MAX_UPLOAD_RETRIES = 5


# ---------------------------------------------------------------------
# PATH RESOLUTION -- the actual bug found on first real test
# ---------------------------------------------------------------------

def _find_project_file(filename: str, must_exist: bool = True) -> str:
    """
    Resolves a project-root file (client_secrets.json, youtube_token.json,
    published_videos.json) across several real candidate locations,
    rather than trusting a bare relative path against whatever
    directory the running process happens to have as its CWD.

    Same root cause and same fix pattern as agent6_1.py's
    _find_venv_python() -- confirmed via a real run: client_secrets.json
    existed on disk the whole time, just not in the one directory a
    bare relative-path lookup happened to check.

    Checks, in order:
      1. Current working directory (works if the notebook happens to
         be run from the project root)
      2. This file's own directory (experiments/agents/)
      3. Two levels up from this file (project root, given this file's
         actual location at experiments/agents/agent10.py)
      4. One level up from this file (in case the layout differs)

    If must_exist=True and nothing is found, raises FileNotFoundError
    listing every path actually checked (not just one guess), so a
    genuinely-missing file is still immediately diagnosable.

    If must_exist=False, returns the PROJECT ROOT candidate (option 3
    above) regardless of whether the file exists yet -- used for files
    this agent creates itself (the token cache, the published-videos
    log) rather than files that must already exist before this runs.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.getcwd(), filename),
        os.path.join(here, filename),
        os.path.join(here, "..", "..", filename),  # experiments/agents/ -> project root
        os.path.join(here, "..", filename),
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate):
            return candidate

    if not must_exist:
        # doesn't exist yet -- return where it SHOULD live (project root)
        return os.path.abspath(os.path.join(here, "..", "..", filename))

    checked = "\n  ".join(os.path.abspath(c) for c in candidates)
    raise FileNotFoundError(
        f"{filename} not found in any of these locations:\n  {checked}\n"
        f"If it exists somewhere else, either move it to one of the paths "
        f"above, or run:\n"
        f"  find ~ -maxdepth 5 -name '{filename}'\n"
        f"to locate it, then add that exact path to this function's "
        f"candidates list."
    )


# ---------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------

def _get_authenticated_service():
    """
    Returns an authenticated YouTube API client. Reuses a cached token
    if valid; refreshes silently if expired-but-refreshable; only opens
    a browser window if no usable credentials exist at all (first run,
    or a fully-expired 7-day testing-mode token).
    """
    creds = None

    # token file may genuinely not exist yet on a first-ever run --
    # that's expected, not an error, so this uses must_exist=False and
    # checks os.path.isfile itself, rather than letting the "raise if
    # missing" path fire on a perfectly normal first run
    token_path = _find_project_file(TOKEN_FILENAME, must_exist=False)
    if os.path.isfile(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  [agent10] cached token expired -- refreshing silently")
            creds.refresh(Request())
        else:
            print("  [agent10] no valid cached token -- opening browser "
                  "for one-time consent")
            secrets_path = _find_project_file(CLIENT_SECRETS_FILENAME, must_exist=True)
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print(f"  [agent10] token saved to {token_path}")

    return build("youtube", "v3", credentials=creds)


# ---------------------------------------------------------------------
# RERUN PROTECTION
# ---------------------------------------------------------------------

def _load_published_log() -> dict:
    log_path = _find_project_file(PUBLISHED_LOG_FILENAME, must_exist=False)
    if not os.path.isfile(log_path):
        return {}
    with open(log_path) as f:
        return json.load(f)


def _save_published_log(log: dict) -> None:
    log_path = _find_project_file(PUBLISHED_LOG_FILENAME, must_exist=False)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)


def _already_published(video_path: str) -> dict | None:
    """
    Returns the existing log entry if this exact video_path was already
    uploaded, or None. Checked BEFORE any API call -- prevents a
    checkpoint re-run during testing from silently creating duplicate
    uploads of the same video.
    """
    log = _load_published_log()
    return log.get(video_path)


# ---------------------------------------------------------------------
# UPLOAD
# ---------------------------------------------------------------------

def _upload_video(youtube, video_path: str, seo: dict) -> str:
    """
    Resumable upload with retry on transient (5xx) errors only --
    a permanent error (e.g. bad request, auth failure) should surface
    immediately, not retry blindly.

    Returns the resulting YouTube video ID.
    """
    body = {
        "snippet": {
            "title": seo["title"],
            "description": seo["description"],
            "tags": seo["tags"],
            "categoryId": seo["category_id"],
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    retry_count = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  [agent10] upload progress: {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES and retry_count < MAX_UPLOAD_RETRIES:
                retry_count += 1
                wait = 2 ** retry_count
                print(f"  [agent10] transient upload error (status "
                      f"{e.resp.status}), retry {retry_count}/{MAX_UPLOAD_RETRIES} "
                      f"in {wait}s")
                time.sleep(wait)
            else:
                raise  # permanent error, or retries exhausted -- surface it

    return response["id"]


def _set_thumbnail(youtube, video_id: str, thumbnail_path: str | None) -> bool:
    """
    Separate required API call -- YouTube's videos.insert does NOT
    accept a thumbnail in the same request; thumbnails.set() must be
    called afterward, referencing the video_id the upload just returned.

    Returns True if a custom thumbnail was set, False if skipped
    (thumbnail_path was None -- Agent 9 already logged why, e.g. Agent
    8's frames were cleaned up before Agent 9 ran). Never raises on a
    missing thumbnail -- YouTube's own auto-generated default is a
    perfectly safe fallback, not a pipeline-blocking failure.
    """
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        print(f"  [agent10] no custom thumbnail available -- YouTube's "
              f"auto-generated default will be used")
        return False

    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
        ).execute()
        return True
    except HttpError as e:
        # confirmed real cause via a real run: YouTube requires the
        # CHANNEL to be phone-verified before custom thumbnails work at
        # all (https://www.youtube.com/verify) -- completely separate
        # from OAuth scopes/GCP config. This function's whole job is to
        # make a thumbnail failure non-fatal, so it must catch its own
        # errors rather than let them propagate into publisher_node()'s
        # outer try/except, which would otherwise discard an already-
        # successful upload over a cosmetic thumbnail issue.
        print(f"  [agent10] thumbnail set FAILED (non-fatal, video upload "
              f"already succeeded): {e}")
        if "permissions to upload and set custom video thumbnails" in str(e):
            print(f"  [agent10] likely cause: channel not phone-verified -- "
                  f"see https://www.youtube.com/verify")
        return False


# ---------------------------------------------------------------------
# NOTIFICATION -- same pattern as Agent 4's _notify_no_stories()
# ---------------------------------------------------------------------

def _notify_success(title: str, video_url: str) -> None:
    """macOS notification on successful upload. Silent no-op on
    non-Mac systems, matching Agent 4's established pattern exactly."""
    safe_title = title.replace('"', "'")[:80]
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{safe_title}" '
            f'with title "AI Newsroom: Uploaded (unlisted)" '
            f'subtitle "{video_url}" '
            f'sound name "Glass"'
        ], check=False, capture_output=True)
    except FileNotFoundError:
        pass


def _notify_failure(error_message: str) -> None:
    """macOS notification on upload failure -- failures here are more
    consequential than most pipeline stages (a real API/quota/auth
    problem needing attention), so this gets its own distinct alert
    rather than silently logging to console only."""
    safe_msg = error_message.replace('"', "'")[:150]
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{safe_msg}" '
            f'with title "AI Newsroom: Upload FAILED" '
            f'sound name "Basso"'
        ], check=False, capture_output=True)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------

def publisher_node(state: dict) -> dict:
    """
    LangGraph-style node wrapper. Reads state["video_path"] (Agent 8)
    and state["seo"] (Agent 9). Writes state["youtube_video_id"] and
    state["youtube_url"].

    Never raises out of this function on an upload failure -- catches,
    notifies via _notify_failure(), records the failure in state, and
    returns. A publish failure should be visible and actionable, not a
    crashed pipeline run with no record of what happened.
    """
    video_path = state["video_path"]
    seo = state["seo"]

    print("=" * 70)
    print("AGENT 10: Publisher")
    print("=" * 70)

    existing = _already_published(video_path)
    if existing:
        print(f"  [agent10] {video_path} was already published as "
              f"{existing['youtube_url']} -- skipping re-upload")
        state["youtube_video_id"] = existing["video_id"]
        state["youtube_url"] = existing["youtube_url"]
        return state

    try:
        youtube = _get_authenticated_service()

        print(f"  [agent10] uploading {video_path} as {PRIVACY_STATUS}...")
        video_id = _upload_video(youtube, video_path, seo)
        video_url = f"https://youtube.com/watch?v={video_id}"

        # save the log entry IMMEDIATELY after a successful upload,
        # before attempting the thumbnail -- a thumbnail failure must
        # never leave a real, successful upload unrecorded (this is
        # exactly what happened on a real run: the crash landed here,
        # and rerun-protection had no record of an upload that had
        # actually already succeeded)
        log = _load_published_log()
        log[video_path] = {
            "video_id": video_id,
            "youtube_url": video_url,
            "title": seo["title"],
            "privacy_status": PRIVACY_STATUS,
            "thumbnail_set": False,  # updated below if it succeeds
        }
        _save_published_log(log)

        thumbnail_set = _set_thumbnail(youtube, video_id, seo.get("thumbnail_path"))
        if thumbnail_set:
            log[video_path]["thumbnail_set"] = True
            _save_published_log(log)

        print(f"  [agent10] uploaded successfully: {video_url}")
        print(f"  [agent10] privacy: {PRIVACY_STATUS} -- awaiting manual review")
        _notify_success(seo["title"], video_url)

        state["youtube_video_id"] = video_id
        state["youtube_url"] = video_url

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"  [agent10] upload FAILED: {error_msg}")
        _notify_failure(error_msg)
        state["youtube_video_id"] = None
        state["youtube_url"] = None
        state["publish_error"] = error_msg

    return state