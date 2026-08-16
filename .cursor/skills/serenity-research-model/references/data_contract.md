# Data Contract

## Input Posts

Accepted formats: CSV, JSON, JSONL, TXT, Markdown.

TweetClaw CSV, JSON, and JSONL exports are acceptable when they contain only public X/Twitter materials. Keep source URLs and retrieval dates when available. Omit credentials, tokens, cookies, request headers, private DMs, drafts, follower lists, account relationship lists, and non-public account metadata.

Preferred columns or keys:

- `id`: platform post id or local id
- `created_at`: ISO date or timestamp
- `author`: account handle
- `text`: post text
- `url`: post URL
- `reply_to`: parent post id or URL
- `quote_of`: quoted post id or URL
- `quoted_author`: quoted account handle, when available
- `quoted_text`: quoted post text, when available
- `retrieved_at`: capture or export timestamp
- `likes`, `retweets`, `replies`, `quotes`, `bookmarks`: optional public engagement counts

For TXT or Markdown, separate posts with a line containing `---` or two blank lines. If no date is present, the script leaves `created_at` blank and evaluation is skipped for that row.

## Output Signals

`signals.csv` fields:

- `signal_id`
- `post_id`
- `created_at`
- `author`
- `url`
- `ticker`
- `asset_type`
- `text`
- `quoted_author`
- `quoted_text`
- `is_quote`
- `engagement_score`
- `theme`
- `subtheme`
- `supply_chain_role`
- `bottleneck_claim`
- `evidence_types`
- `catalysts`
- `risk_markers`
- `horizon`
- `conviction_score`
- `conviction_reasons`
- `model_tags`

## Price Data

Use one CSV per ticker in a price directory:

- filename: `<TICKER>.csv`, for example `AXTI.csv`
- required columns: `date`, `close`
- date format: `YYYY-MM-DD` preferred
- close: split-adjusted close preferred when available

Evaluation uses the first available trading date on or after the post date.
