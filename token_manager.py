import os

def get_allvalue_access_token():
    token = os.environ.get("ALLVALUE_PERMANENT_TOKEN")
    if not token:
        raise ValueError("Missing permanent token! Please set ALLVALUE_PERMANENT_TOKEN.")
    return token