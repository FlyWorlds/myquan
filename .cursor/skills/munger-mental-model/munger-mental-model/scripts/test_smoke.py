#!/usr/bin/env python3
"""Quick smoke check for data.py implementation."""

from __future__ import annotations

import sys
import data

def main():
    print("Testing data.init()...")
    data.init()
    print("✓ data.init() succeeded")

    print()
    print("Testing data.fetch_fina(['000001.SZ'], None)...")
    try:
        df = data.fetch_fina(['000001.SZ'], None)
        print(f"✓ fetch_fina() returned DataFrame with shape {df.shape}")
        print(f"  Columns: {df.columns.tolist()}")
        if not df.empty:
            print(f"  First row:")
            for col in df.columns:
                val = df.iloc[0][col]
                print(f"    {col}: {val}")
    except Exception as e:
        print(f"✗ fetch_fina() failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()
    print("All tests passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
