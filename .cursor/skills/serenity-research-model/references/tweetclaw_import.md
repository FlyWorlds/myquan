# TweetClaw Import Notes

TweetClaw can be used as an optional public X/Twitter capture source for this skill. Use it to prepare post, reply, search, or user-post exports before running the existing `extract`, `clean`, `auto-review`, `evaluate`, and `report` pipeline.

## Boundary

- Include public post text, public quoted text, source URLs, authors, post ids, timestamps, retrieval timestamps, public engagement counts, and public aggregate follower counts when relevant.
- Exclude credentials, cookies, access tokens, request headers, private DMs, drafts, unpublished posts, raw session material, follower lists, account relationship lists, and non-public account metadata.
- Treat public aggregate follower and engagement counts as context only. They do not prove investment quality, account performance, or private returns.
- Preserve enough source context to separate Serenity's own text from quoted or replied-to text.

## Field Mapping

| Pipeline column | TweetClaw or export fields to map |
| --- | --- |
| `id` | `id`, `tweet_id`, `post_id` |
| `created_at` | `created_at`, `createdAtISO`, `date` |
| `author` | `author`, `username`, `screen_name` |
| `text` | `text`, `full_text`, `content` |
| `url` | `url`, `tweet_url`, `post_url` |
| `quoted_author` | `quoted_author`, `quotedAuthor` |
| `quoted_text` | `quoted_text`, `quotedText` |
| `likes` | `likes`, `like_count` |
| `retweets` | `retweets`, `reposts`, `repost_count` |
| `replies` | `replies`, `reply_count` |
| `quotes` | `quotes`, `quote_count` |
| `bookmarks` | `bookmarks`, `bookmark_count` |
| `retrieved_at` | `retrieved_at`, `captured_at`, `exported_at` |

The current extractor reads the canonical pipeline columns directly. If an export uses alternate names, normalize it to the data contract before running the pipeline.

## Validation

Run the normal source and cleaning steps after normalizing a TweetClaw export:

```bash
python scripts/serenity_mvp.py extract --posts tweetclaw-public-posts.csv --out run1
python scripts/serenity_mvp.py clean --signals run1/signals.csv --posts tweetclaw-public-posts.csv --out run1
```

Then inspect `manual_review_queue.csv` and `quote_relationships.csv` before treating any ticker row as Serenity's own forward thesis.
