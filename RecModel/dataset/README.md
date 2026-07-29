# Data Directory

Place the Foursquare NYC dataset (`dataset_TSMC2014_NYC.csv`) here or
specify its path via `--data_path` when running experiments.

## Dataset Format

| Column | Description |
|--------|-------------|
| userId | Anonymous user identifier |
| venueId | Anonymous venue (POI) identifier |
| venueCategoryId | Numeric category ID |
| venueCategory | Human-readable category name |
| latitude | GPS latitude |
| longitude | GPS longitude |
| timezoneOffset | UTC offset in minutes |
| utcTimestamp | Check-in timestamp |

## Dataset Source

Foursquare NYC check-in dataset (TSMC2014), collected from
Foursquare between April 2012 and February 2013.

The dataset is provided as `dataset_TSMC2014_NYC.csv` in the project root.
Copy or symlink it to this directory, or run with:
```bash
python -m src.run_experiments --data_path ../dataset_TSMC2014_NYC.csv
```
