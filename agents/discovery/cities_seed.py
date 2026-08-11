"""Starter set of major US cities to search first.

This is a pilot list (top ~25 metros by population, spread across 20 states),
not full national coverage -- that's the point. Validate lead quality and
API cost on this batch before expanding.

To scale up later: add more (city, state, lat, lng) rows here, ideally
sourced from a full US Census places dataset rather than hand-typed. Same
pipeline code handles any number of cities.

radius_m is the search radius in meters around the city centroid.
"""

SEED_CITIES = [
    ("New York", "NY", 40.7128, -74.0060),
    ("Los Angeles", "CA", 34.0522, -118.2437),
    ("Chicago", "IL", 41.8781, -87.6298),
    ("Houston", "TX", 29.7604, -95.3698),
    ("Phoenix", "AZ", 33.4484, -112.0740),
    ("Philadelphia", "PA", 39.9526, -75.1652),
    ("San Antonio", "TX", 29.4241, -98.4936),
    ("San Diego", "CA", 32.7157, -117.1611),
    ("Dallas", "TX", 32.7767, -96.7970),
    ("Austin", "TX", 30.2672, -97.7431),
    ("Jacksonville", "FL", 30.3322, -81.6557),
    ("San Jose", "CA", 37.3382, -121.8863),
    ("Fort Worth", "TX", 32.7555, -97.3308),
    ("Columbus", "OH", 39.9612, -82.9988),
    ("Charlotte", "NC", 35.2271, -80.8431),
    ("Indianapolis", "IN", 39.7684, -86.1581),
    ("San Francisco", "CA", 37.7749, -122.4194),
    ("Seattle", "WA", 47.6062, -122.3321),
    ("Denver", "CO", 39.7392, -104.9903),
    ("Oklahoma City", "OK", 35.4676, -97.5164),
    ("Nashville", "TN", 36.1627, -86.7816),
    ("Washington", "DC", 38.9072, -77.0369),
    ("Boston", "MA", 42.3601, -71.0589),
    ("Portland", "OR", 45.5152, -122.6784),
    ("Las Vegas", "NV", 36.1699, -115.1398),
]

DEFAULT_RADIUS_M = 15000
