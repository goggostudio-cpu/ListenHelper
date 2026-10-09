# EnglishFlow — Daily Content Repository

Listening practice app for Android. This repository hosts the **"오늘의 영어" (Today's English)** daily content that the EnglishFlow app downloads from the `content/` directory.

## Repository contents

- `content/` — daily English-learning content files (`YYYY-MM-DD-<slug>-<type>.json`)
- `scripts/generate_week.py` — weekly batch generator (Python 3, standard library only)
- `privacy-policy.html` — app privacy policy (served via GitHub Pages)

## Content format

7 types: `quote`, `story`, `knowledge`, `business`, `essay`, `travel`, `dialogue`.

| type | top-level fields |
|---|---|
| quote / story / knowledge / business / essay / travel | `en`, `ko`, `subject`, `expressions[]` |
| dialogue | `subject`, `lines[]` (speaker/en/ko), `expressions[]` |

`expressions[]` items: `{ "en", "ko", "example", "exampleKo"(optional) }`.

File name example: `2026-10-12-<slug>-<type>.json`. The app shows a file as **"오늘"(today)** when its date matches the current date.

## Weekly generation (recommended)

One command produces the next 7 days (next Monday → Sunday), one file per category.

1. Get a free Gemini API key: <https://aistudio.google.com/apikey>
2. Copy `scripts/.env.example` to `scripts/.env` and set `GEMINI_API_KEY=...` (`scripts/.env` is gitignored).
3. Generate:

   ```text
   python scripts/generate_week.py
   ```

   Options: `--start YYYY-MM-DD`, `--days N`, `--types ...`, `--model ...`.

4. Review the JSON files in `content/` and edit anything you want to change.
5. Deploy:

   ```text
   git add content/
   git commit -m "Add weekly daily content (MM/DD-MD/DD)"
   git push
   ```

   The app picks up the new files on its next refresh.

### Inspect the format without a key

```text
python scripts/generate_week.py --demo --content-dir <some-temp-folder>
```

Writes built-in samples so you can inspect the format/validation without an API key. Do not commit demo files to `content/`.

### Validation

The generator validates every item before writing:

- JSON parses; `en`/`ko` non-blank; word-count ranges per type.
- `expressions`: 3-5 items, each with `en`, `ko`, `example`.
- `dialogue`: at least 4 lines, two speakers, each line non-blank.
- File-name rule + no duplicate date/slug (existing dates are skipped).

## Scheduled automation (완전 무인)

`.github/workflows/daily-content.yml` runs **every day at 00:05 KST** and keeps a rolling
buffer of content ahead of today:

1. Computes today (KST) and generates `today → today+7` (existing dates are skipped,
   so normally only 1 new item is created per day).
2. The generator auto-retries transient API errors (429/500/503/timeout) and falls back
   to another Gemini model when the primary model's free-tier quota is exhausted.
3. Any new files are committed and pushed to `main` automatically.
4. You can also trigger it manually from **Actions → Daily content generator → Run workflow**.

### One-time setup

1. Push this repository (including `.github/workflows/` and `scripts/`).
2. Add the API key as an Actions secret named `GEMINI_API_KEY`
   (Settings → Secrets and variables → Actions) in this repository.
