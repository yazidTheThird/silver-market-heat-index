"""Import normalized, verified weekly completed sales; never scrape asking prices.
Usage: python import_sales.py export.csv
Use data/completed_sales.csv's header; see README for field definitions.
"""
import argparse
import os
import pandas as pd
from mhi.evidence import SALES, SALES_COLUMNS, validate_sales


def ingest(path, destination=SALES):
    incoming = validate_sales(pd.read_csv(path))
    existing = validate_sales(pd.read_csv(destination)) if os.path.exists(destination) else pd.DataFrame(columns=SALES_COLUMNS)
    keys = ['period_start', 'source', 'query_id', 'segment', 'currency']
    # An import can explicitly correct the same source period without duplicating it.
    merged = pd.concat([existing, incoming], ignore_index=True).drop_duplicates(keys, keep='last')
    merged = validate_sales(merged).sort_values(keys)
    temp = destination + '.tmp'
    merged.to_csv(temp, index=False)
    os.replace(temp, destination)
    return len(incoming)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    args = parser.parse_args()
    print(f'Imported {ingest(args.csv)} verified weekly records. Run python run.py --rebuild to refresh.')
