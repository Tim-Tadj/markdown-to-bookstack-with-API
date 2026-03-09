import os

import requests
import urllib3
from dotenv import load_dotenv

# --- Configuration ---
# Set the old and new tag names (keys) and values
OLD_TAG_NAME = "BookStack"
OLD_TAG_VALUE = "Lags"  # Leave as "" if the tag currently has no value

NEW_TAG_NAME = "BookStack"
NEW_TAG_VALUE = "Tags"  # Leave as "" if you want the new tag to have no value

# Load credentials from .env
load_dotenv()
BASE_URL = os.getenv("BOOKSTACK_BASE_URL", "").rstrip("/")
TOKEN_ID = os.getenv("BOOKSTACK_TOKEN_ID")
TOKEN_SECRET = os.getenv("BOOKSTACK_TOKEN_SECRET")

# Check for insecure TLS flag
INSECURE_ENV = os.getenv("BOOKSTACK_INSECURE", "0")
VERIFY_SSL = False if INSECURE_ENV.lower() in ["1", "true", "yes"] else True

# Suppress warnings if we are intentionally bypassing SSL verification
if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Setup ---
if not all([BASE_URL, TOKEN_ID, TOKEN_SECRET]):
    print("Error: Missing API credentials. Please check your .env file.")
    exit(1)

HEADERS = {
    "Authorization": f"Token {TOKEN_ID}:{TOKEN_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def get_endpoint(item_type):
    """Maps BookStack item types to their plural API endpoints."""
    mapping = {
        "page": "pages",
        "chapter": "chapters",
        "book": "books",
        "bookshelf": "bookshelves",
    }
    return mapping.get(item_type)


def main():
    # Build the specific BookStack search syntax (e.g., [Name=Value] or [Name])
    search_query = (
        f"[{OLD_TAG_NAME}={OLD_TAG_VALUE}]" if OLD_TAG_VALUE else f"[{OLD_TAG_NAME}]"
    )
    print(f"Searching for items with tag query: '{search_query}'...")

    # Step 1: Search for all items using the old tag
    search_url = f"{BASE_URL}/api/search"
    search_params = {
        "query": search_query,
        "count": 100,
    }

    search_response = requests.get(
        search_url, headers=HEADERS, params=search_params, verify=VERIFY_SSL
    )

    # Better error handling for 403s or other auth issues
    if search_response.status_code != 200:
        print(f"API Error ({search_response.status_code}): {search_response.text}")
        exit(1)

    search_data = search_response.json().get("data", [])

    if not search_data:
        print(f"No items found matching the query '{search_query}'.")
        return

    print(f"Found {len(search_data)} item(s). Processing...")

    # Step 2 & 3: Iterate over results and fetch current tags
    for item in search_data:
        item_id = item.get("id")
        item_type = item.get("type")
        item_name = item.get("name")
        endpoint = get_endpoint(item_type)

        if not endpoint:
            print(f"Skipping unknown item type: {item_type}")
            continue

        item_url = f"{BASE_URL}/api/{endpoint}/{item_id}"

        # Fetch the full item details to get the current tags
        detail_response = requests.get(item_url, headers=HEADERS, verify=VERIFY_SSL)
        if detail_response.status_code != 200:
            print(f"Failed to fetch {item_type} '{item_name}' (ID: {item_id}).")
            continue

        current_tags = detail_response.json().get("tags", [])

        # Step 4: Modify the tags array locally
        updated = False
        for tag in current_tags:
            # Safely get current values, defaulting to empty string if None
            current_name = tag.get("name", "") or ""
            current_val = tag.get("value", "") or ""
            target_val = OLD_TAG_VALUE or ""

            # Use .strip() for spaces and .lower() to make matching completely case-insensitive
            if (
                current_name.strip().lower() == OLD_TAG_NAME.strip().lower()
                and current_val.strip().lower() == target_val.strip().lower()
            ):
                tag["name"] = NEW_TAG_NAME
                tag["value"] = NEW_TAG_VALUE
                updated = True

        if not updated:
            print(f"Tag exact match not found on {item_type} '{item_name}'. Skipping.")
            continue

        # Step 5: Send the PUT request with the full, modified tags array
        update_response = requests.put(
            item_url, headers=HEADERS, json={"tags": current_tags}, verify=VERIFY_SSL
        )

        if update_response.status_code == 200:
            print(f"✅ Successfully updated {item_type} '{item_name}' (ID: {item_id})")
        else:
            print(
                f"❌ Failed to update {item_type} '{item_name}'. Error: {update_response.text}"
            )

    print("\nTag renaming process complete!")


if __name__ == "__main__":
    main()
