import requests
import os
import json
import time
import logging

logger = logging.getLogger(__name__)

ALLVALUE_CLIENT_ID = os.environ.get("ALLVALUE_CLIENT_ID")
ALLVALUE_CLIENT_SECRET = os.environ.get("ALLVALUE_CLIENT_SECRET")
ALLVALUE_REDIRECT_URI = os.environ.get("ALLVALUE_REDIRECT_URI")
ALLVALUE_AUTHORIZE_URL = os.environ.get("ALLVALUE_AUTHORIZE_URL")
ALLVALUE_TOKEN_URL = os.environ.get("ALLVALUE_TOKEN_URL")
TOKEN_FILE = "allvalue_token.json"


class TokenRetrievalError(Exception):
    """自定义异常，用于表示 Token 获取失败。"""
    pass


def get_token_data(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in {filename}, resetting.")
        return None


def get_allvalue_access_token(code=None):
    token_data = get_token_data(TOKEN_FILE)

    if token_data and token_data.get("expires_at", 0) > time.time():
        logger.info("Using cached access token.")
        return token_data["access_token"]

    def build_data_dict(grant_type, token=None):
        data = {
            "grantType": grant_type,
            "clientId": ALLVALUE_CLIENT_ID,
            "clientSecret": ALLVALUE_CLIENT_SECRET,
        }
        if code:
            data["code"] = code
            data["redirectUri"] = ALLVALUE_REDIRECT_URI
        elif token and token_data.get("refresh_token"):
            data["refreshToken"] = token_data["refresh_token"]
        return data

    try:
        data = build_data_dict("authorization_code", code) if code else build_data_dict("refresh_token")
        url = ALLVALUE_TOKEN_URL
        resp = requests.post(url, data=data)
        resp.raise_for_status()
        token_info = resp.json()

        if "access_token" not in token_info:
            logger.error(f"Token response missing access_token: {token_info}")
            raise TokenRetrievalError("Token response missing access_token")

        expires_in = token_info.get("expires_in")
        expires_at = time.time() + expires_in if expires_in else None

        token_data = {
            "access_token": token_info["access_token"],
            "refresh_token": token_info.get("refresh_token"),
            "expires_at": expires_at,
        }
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f)

        return token_data["access_token"]

    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving token: {e}")
        if resp is not None:
            logger.error(f"Response status code: {resp.status_code}")
            logger.error(f"Response content: {resp.content}")
        raise TokenRetrievalError(f"Failed to retrieve token: {e}")
    except (KeyError, TypeError) as e:
        logger.exception("解析token信息出错:")
        raise TokenRetrievalError(f"解析token信息出错:{e}")
    except Exception as e:
        logger.exception("获取token时发生未知错误:")
        raise TokenRetrievalError(f"获取token时发生未知错误:{e}")