import os
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import HTTPException, Header

from jose import jwt
import requests


def set_up():
    load_dotenv()

    config = {
        "DOMAIN": os.getenv("AUTH0_DOMAIN", "dev-kpkwtczj2hsz5r1w.us.auth0.com"),
        "API_AUDIENCE": os.getenv(
            "AUTH0_API_AUDIENCE", "https://auth0-dev-api.stak.cc"
        ),
        "ISSUER": os.getenv(
            "AUTH0_ISSUER", "https://dev-kpkwtczj2hsz5r1w.us.auth0.com/"
        ),
        "ALGORITHMS": os.getenv("AUTH0_ALGORITHMS", "RS256"),
    }
    return config


def get_token_auth_header(auth0: str) -> str:
    parts = auth0.split()

    if parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401, detail="Authorization header must start with Bearer"
        )

    elif len(parts) == 1:
        raise HTTPException(status_code=401, detail="Token not found")

    elif len(parts) > 2:
        raise HTTPException(
            status_code=401, detail="Authorization header must be Bearer token"
        )

    token = parts[1]
    return token


def get_jwks() -> dict:
    url = f"https://{set_up()['DOMAIN']}/.well-known/jwks.json"
    res = requests.get(url)
    res.raise_for_status()
    return res.json()


def verify_token(token: str, audience: str, algorithms: List[str], jwks: Dict) -> Dict:
    unverified_header = jwt.get_unverified_header(token)
    if "kid" not in unverified_header:
        raise HTTPException(status_code=401, detail="Authorization malformed.")

    rsa_key = {}
    for key in jwks["keys"]:
        if key["kid"] == unverified_header["kid"]:
            rsa_key = {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }
    if not rsa_key:
        raise HTTPException(status_code=401, detail="Unable to find appropriate key")

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=algorithms,
            audience=audience,
            issuer=f'https://{set_up()["DOMAIN"]}/',
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")

    except jwt.JWTClaimsError:
        raise HTTPException(status_code=401, detail="Invalid claims")

    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=400, detail="Unable to parse authentication token."
        )


# This authenticates to the authenticated user via Auth0 token
async def get_current_user(
    auth0: str = Header(..., description="Auth0 header"),
):

    access_token = get_token_auth_header(auth0)

    jwks = get_jwks()
    payload = verify_token(access_token, set_up()["API_AUDIENCE"], ["RS256"], jwks)
    return payload


def check_user_data(
    company_id: str, current_user: dict, user_uuid: str | None = None
) -> bool:
    # Check that the companyID used in the api call matches the company Id in the payload of the accessToken
    if current_user["user_metadata"]["companyId"] != company_id:
        raise HTTPException(status_code=401, detail="Unauthorized access.")
