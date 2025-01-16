import os

def get_allvalue_access_token():
    token = ""
    if not token:
        raise ValueError("Missing permanent token! Please set ALLVALUE_PERMANENT_TOKEN.")
    return token