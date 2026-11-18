# United States area catalog

`us_places_2025.csv` contains 32,058 Census places in all 50 U.S. states and the District of Columbia, derived from the U.S. Census Bureau's 2025 National Places Gazetteer. It includes incorporated places and Census-designated places, not every informal neighborhood or locality. Coordinators may add missing general areas.

Source: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2025.html
Download: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip

Columns retained: state abbreviation, Census GEOID, display name, representative latitude, and representative longitude. Puerto Rico is excluded from this 50-state/DC catalog. Common legal-type suffixes are removed from display names unless needed to distinguish names within a state. GEOIDs are retained for stable identifiers. Coordinates are Census representative points, rounded by their published precision; they are not resident addresses or device locations.

Imported from the bundled CSV by `python manage.py import_us_areas`. No external requests are made when residents search. Original source ZIP is not needed to run the app. Existing local area IDs and resident profiles are preserved during repeat imports.
