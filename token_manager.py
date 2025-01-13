import os

def get_allvalue_access_token():
    #todo: 添加值
    token = "test"
    if not token:
        raise ValueError("Missing permanent token! Please set ALLVALUE_PERMANENT_TOKEN.")
    return token