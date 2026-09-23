# QA Preview Publishing (Phase 5)

Storage abstraction and notification publishing for the autonomous QA pipeline. This stage takes the
media produced by Phase 4, hosts it, and reports the outcome on the pull request.

## What it does

1. Uploads the compressed MP4, preview GIF and (on failure) the Playwright trace to Cloudflare R2,
   falling back to GitHub Actions artifacts when R2 is unconfigured or unreachable.
2. Maintains **exactly one** QA comment per pull request, edited in place on every push.
3. Posts a non-blocking Slack thread reply.

## Configuration

Storage credentials are read from the environment. In CI they arrive from either of two
sources: GitHub Actions secrets named after the `R2_*` variables below, or SOPS decryption of
`.env.qa.enc`. A GitHub secret overrides the same key from the encrypted file, and an unset
secret leaves the decrypted value in place. `R2_ENDPOINT_URL` is read from `.env.qa.enc` only.

| Variable | Required | Purpose |
| :--- | :--- | :--- |
| `R2_ACCOUNT_ID` | Yes¹ | Cloudflare account, used to derive the S3 endpoint |
| `R2_ACCESS_KEY_ID` | Yes | R2 access key |
| `R2_SECRET_ACCESS_KEY` | Yes | R2 secret key |
| `R2_BUCKET` | Yes | Destination bucket |
| `R2_PUBLIC_BASE_URL` | Yes | Public origin (`https://media.example.com` or an `r2.dev` subdomain) |
| `R2_ENDPOINT_URL` | No | Overrides the derived endpoint, for S3 or a compatible service |
| `GH_TOKEN` / `GITHUB_TOKEN` | Yes | Used to read, create and edit PR comments |
| `QA_BOT_LOGIN` | No | Pins comment-authorship matching to a specific account |
| `SLACK_CHANNEL`, `SLACK_TOKEN`, `SLACK_THREAD` | No | Slack notification; skipped entirely when unset |
| `QA_ARTIFACT_DIR` | No | Staging directory for the artifact fallback (default `qa-artifacts`) |

¹ Not required when `R2_ENDPOINT_URL` is set explicitly.

**Public access is required, not optional.** Links are built from `R2_PUBLIC_BASE_URL` rather than
presigned URLs, because a presigned R2 URL expires after at most seven days and would silently break
the video link in every older pull request comment.

## One-time bucket setup

Installs the rule that expires QA media after 30 days. Needs bucket admin permission, so it is run
once by an operator rather than by the pipeline:

```bash
qa-publish --apply-lifecycle
```

The rule is scoped to the `qa/` prefix, so objects outside it are unaffected. Because
`PutBucketLifecycleConfiguration` replaces a bucket's entire configuration, the command reads the
existing rules and merges: every unrelated rule is preserved, and re-running replaces only the rule
carrying the QA ID.

## Publishing a run

```bash
qa-publish \
  --repo "$GITHUB_REPOSITORY" \
  --pr "${{ github.event.number }}" \
  --sha "${{ github.event.pull_request.head.sha }}" \
  --test-result results/run.json \
  --media-result results/media.json \
  --branch-result results/branch.json \
  --run-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
```

**Pass the PR head SHA, not `GITHUB_SHA`.** On a `pull_request` event `GITHUB_SHA` is the synthetic
merge commit of `refs/pull/N/merge`, which appears nowhere in the PR's commit list — reviewers would
see a SHA they cannot find, and media would be keyed by a commit that is recreated whenever the base
branch moves. When `--sha` and `--pr` are omitted they are read from `GITHUB_EVENT_PATH`, which
resolves to the head SHA already, so both flags can be dropped inside a workflow.

Publishing fails fast when no SHA can be resolved. An empty SHA would collapse every run onto one
object key and serve the previous run's cached media beside the current run's text.

`--dry-run` renders the comment to stdout without uploading or posting, which is the quickest way to
iterate on formatting.

`--media-result` consumes the JSON written by `qa-media --result-json`.

## Exit codes

| Code | Meaning |
| :--- | :--- |
| `0` | Comment published. Media may have fallen back to artifacts; that is a degraded success, not a failure. |
| `1` | Missing arguments, an unreadable test result, or the PR comment could not be published. |

Media upload failure never returns `1`. A missing preview is an inconvenience; a red pipeline on a
working pull request is a broken signal.

## Object layout

```
qa/{owner}_{repo}/pr-{number}/{commit}/{filename}
```

The commit is part of the path deliberately. GitHub proxies and caches images by URL, so reusing one
key across pushes would leave reviewers looking at a cached GIF of the previous run while the comment
text describes the current one.

## Artifact fallback

Python cannot upload a workflow artifact directly. When R2 is unavailable, media is copied into a
staging directory whose path is published to `$GITHUB_OUTPUT` as `qa_artifact_dir`. A workflow step
guarded by `if: always()` collects it:

```yaml
- name: Publish QA results
  id: qa_publish
  run: qa-publish --repo "$GITHUB_REPOSITORY" --pr "${{ github.event.number }}" ...

- name: Upload QA media
  if: always() && steps.qa_publish.outputs.qa_artifact_dir != ''
  uses: actions/upload-artifact@v4
  with:
    name: qa-media
    path: ${{ steps.qa_publish.outputs.qa_artifact_dir }}
```

**Known limitation**: an artifact is an authenticated zip download with no per-file address, so media
stored this way is linked rather than embedded. The comment degrades to a download link and states
why. Tracked as item A.2 in the implementation plan's deferred list.

## Comment idempotency

Every comment opens with the hidden marker `<!-- qa-preview-bot -->`, which is invisible in rendered
markdown. Before posting, the publisher pages through the PR's entire comment list and matches on the
marker **and** authorship.

Both conditions are load-bearing:

- **Marker only** would let a reviewer who quotes the bot's comment have their own words silently
  overwritten.
- **First page only** would miss the bot's comment on a busy PR and post duplicates.

Identity is resolved in this order:

1. `QA_BOT_LOGIN`, when configured.
2. The `/user` endpoint, which works for a personal access token.
3. `github-actions[bot]`, when `GITHUB_ACTIONS=true`. A workflow `GITHUB_TOKEN` cannot call `/user`,
   but every comment it authors belongs to that account, so the identity is still known exactly.
4. Otherwise, any machine account — which still excludes humans, but is not a verified match.

**Duplicate removal is disabled on that last path.** Deleting a comment on the strength of an
unverified match risks destroying another bot's comment, which is worse than leaving a duplicate.
Set `QA_BOT_LOGIN` to restore exact matching outside GitHub Actions.

If a concurrent run has left more than one marked comment, the newest is updated and the rest are
deleted. Because read-then-create is not atomic, the publisher also re-reads after creating a
comment and collapses anything a racing run posted in between, so each completed call restores the
one-comment invariant. Phase 6's `cancel-in-progress` prevents nearly all occurrences; these are the
backstop.

Comment discovery stops at 2,000 comments (20 pages). Beyond that the publisher logs a warning
rather than silently posting a duplicate.
