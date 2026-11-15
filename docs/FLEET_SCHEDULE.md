# Trickster Fleet Schedule — configuration and limitations

This module is included in the normal Windows Trickster application. Open **Fleet Schedule** in the sidebar. The installer and the ordinary profile manager remain unchanged.

## Machines

Install the same version of Trickster on all 13 laptops. Set `machine_index` to a different number from 0 through 12 on each. The layout is 133/133 profiles on the two 32 GB machines (24 worker limit each), then 67 profiles on eight of the 16 GB machines and 66 on three (12 workers each). These are concurrency ceilings, **not tested performance guarantees**.

Each installation needs access to an **identical global profile inventory**. If `profile_ids` is empty, the scheduler attempts to list it from the configured Local API and sort by profile ID. If the 13 machines have differing profile inventories, supply the same ordered list of 1,000 profile IDs manually on each machine.

## Manifest format

Use the Fleet panel to save this JSON, replacing the empty campaigns array with your platform's actual catalog:

```json
{
  "machine_index": 0,
  "timezone": "Australia/Melbourne",
  "operating_hour": 11,
  "api_url": "http://127.0.0.1:53200",
  "api_token": "",
  "profile_ids": [],
  "campaigns": [
    {
      "id": "campaign-01",
      "creator_url": "https://your-own-platform.example/creator/one",
      "link_selector": "a[href]",
      "quality_selector": "",
      "clips": [
        {
          "id": "clip-001",
          "href": "/clip/001",
          "duration_seconds": 20
        }
      ]
    }
  ]
}
```

The actual configuration requires **10 campaigns of exactly 100 clips each**, with unique IDs within each campaign. The sample above is intentionally incomplete and cannot run until those clips have been supplied. This program does not fabricate your platform's clip URLs or CSS selectors.

The four passes contain 20, 30, 40 and 10 clips respectively for each profile. Each profile samples 10 distinct clips per campaign, daily, shuffled deterministically using the date and profile ID, so restarted runs do not change the day's choices. After a successful clip, its ID is recorded in `fleet_ledger.json`.

## API integration

This code uses POST `/api/v2/profile-list`, `profile-open`, and `profile-close`. It supports the real ixBrowser Local API and Trickster's compatible implementation for the fields it uses. Each worker owns its own HTTP client and Playwright CDP connection. Concurrent Local API requests are throttled globally to three. API profile-close runs in a `finally` block for each profile.

## Playback

Navigation begins from the supplied `creator_url` and clicks a matching link. The site-specific `href` and `link_selector` must accurately describe your own site. It never silently substitutes direct media URL navigation. It blocks images and fonts, attempts to select 360p and falls back to 480p if a quality selector is provided, and waits between 60% and 115% of the declared clip duration with small pauses.

## Operating window, proxy and RAM

The scheduler uses the configured local time zone, runs within an 8-hour window each day and waits for the next day. Workers check the deadline before each clip and close profiles through the Local API after a batch.

`fleet_bandwidth.json` records an **estimate** from Chrome DevTools encoded transfer lengths. The scheduler stops starting additional clips for a profile at an estimated 80 GiB per calendar month (below the desired 100 GB ceiling). This is **not guaranteed proxy billing data**: proxy overhead, other processes, and network traffic outside Chrome may be missing. Set up proxy-provider usage limits separately for a hard 100 GB cap.

## Not yet verified

* Actual browser startup and creator-page clicking on your platform
* Sustained 24 or 12 concurrent browser processes on the specified laptop RAM
* User-data and proxy-usage consistency across 13 machines
* Completion of 100 clips per profile inside eight hours, which depends on actual media duration and load time

ClipEngine remains the video editing/production application; the fleet browser scheduler belongs to Trickster. It does not require replacing the ClipEngine user interface.
