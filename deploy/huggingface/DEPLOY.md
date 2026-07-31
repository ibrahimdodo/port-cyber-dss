# Deploying to Hugging Face Spaces

The Space README needs YAML frontmatter that Spaces reads as configuration. That
frontmatter renders as an ugly metadata table on GitHub, so it lives here rather
than in the repo's own README, and `sync.sh` swaps it in at push time.

Nothing else differs between the GitHub repo and the Space.

## One-time setup

1. Create the Space at <https://huggingface.co/new-space> — SDK **Streamlit**,
   hardware **CPU basic** is enough (the Monte Carlo is vectorised numpy and runs
   in well under a second).
2. Add it as a git remote:

   ```bash
   git remote add space https://huggingface.co/spaces/<user>/portscra
   ```

3. Authenticate. Spaces uses a write token as the password:
   <https://huggingface.co/settings/tokens>

##每 deploy

```bash
./deploy/huggingface/sync.sh <user>/portscra
```

The script pushes the current `main` to the Space with the Space README swapped
in, leaving your working tree untouched.

## Why it works without extra packaging

`app/streamlit_app.py` falls back to `src/` on the path when `portscra` is not
pip-installed, and the whole repo is pushed, so the import resolves either way.
`requirements.txt` at the root is what Spaces installs.

## Things that would break it, and why they do not

* **No writable home directory.** `signals.SignalCache` falls back to a temp
  directory, and an unwritable cache degrades to re-fetching rather than raising.
* **No network.** Every feed lookup returns a `FeedResult` marked not-ok; the
  dashboard shows the signal as unset rather than as clean. Verify with
  `python scripts/refresh_signals.py --offline --cache-dir /tmp/cold`.
* **No AIS data.** The dashboard reads no files from disk. Only the notebooks use
  the parquet, and that is committed at 82 kB.

## After deploying

Check the Space logs for the first run — the live feed fetches happen on the
Suppliers tab and are the only outbound calls the app makes.
