import rcdb
import os
import json

import argparse

def main(query, min_run, max_run):
    db = rcdb.RCDBProvider(os.environ.get('RCDB_CONNECTION'))
    table = db.select_runs(str(query),min_run,max_run).get_values(['event_count','polarimeter_converter'],True)
    print(json.dumps(table))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Python script to return an RCDB query."
    )
    
    parser.add_argument(
        "rcdb_query",
        type=str,
        help="RCBD Query"
    )
    
    parser.add_argument(
        "min_runnumber",
        type=int,
        help="Min Run Number"
    )
    
    parser.add_argument(
        "max_runnumber",
        type=int,
        help="Max Run Number"
    )
    
    args = parser.parse_args()
    
    main(args.rcdb_query, args.min_runnumber, args.max_runnumber)
