from apify_client import ApifyClient
import os

client = ApifyClient(os.getenv("APIFY_API_TOKEN"))

# Run a quick actor to see the Run object structure
run = client.actor("compass/google-maps-reviews-scraper").call(run_input={
    "startUrls": [{"url": "https://www.google.com/maps/search/test"}],
    "maxReviews": 1
})

print("Run type:", type(run))
print("\nRun attributes:")
print(dir(run))

print("\nTrying to get dataset ID:")
try:
    print("run['default_dataset_id']:", run['default_dataset_id'])
except Exception as e:
    print(f"Dictionary access failed: {e}")

try:
    print("run.default_dataset_id:", run.default_dataset_id)
except Exception as e:
    print(f"Attribute access failed: {e}")

# Check if it's a dict-like object
print("\nIs dict:", isinstance(run, dict))
print("Has __getitem__:", hasattr(run, '__getitem__'))
