"""Repository tests must never select the production database ledger."""
import os

os.environ["HOLDINGS_STORAGE"] = "local_json"
