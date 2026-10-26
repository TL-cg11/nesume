"""시드 계정 토큰(D6 app/app/auth/seed.py의 test-user1·test-user2·test-mentor1·test-operator1·svc-batch).

Cognito USER_PASSWORD_AUTH로 로그인해 액세스 토큰을 받는다. 비밀번호는 SEED_PASSWORD 환경변수(시드와 같음).
"""
from __future__ import annotations

import base64
import json
import os

import boto3

ROLE_USERNAMES = {
    "user": "test-user1", "user2": "test-user2", "mentor": "test-mentor1",
    "operator": "test-operator1", "system": "svc-batch",
}


def _sub(token: str) -> str:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["sub"]


class CognitoAccounts:
    def __init__(self, *, client_id: str, password: str, domain: str, region: str, endpoint: str | None = None):
        self.idp = boto3.client("cognito-idp", region_name=region, endpoint_url=endpoint)
        self.client_id, self.password, self.domain = client_id, password, domain
        self._tokens: dict[str, str] = {}

    @classmethod
    def from_env(cls) -> "CognitoAccounts":
        return cls(
            client_id=os.environ.get("RUNNER_COGNITO_CLIENT_ID") or os.environ["COGNITO_CLIENT_ID"],
            password=os.environ["SEED_PASSWORD"],
            domain=os.environ.get("SEED_EMAIL_DOMAIN", "example.com"),
            region=os.environ.get("AWS_REGION", "ap-northeast-2"),
            endpoint=os.environ.get("COGNITO_LOCAL_ENDPOINT"),
        )

    def token(self, role: str) -> str:
        if role not in self._tokens:
            res = self.idp.initiate_auth(
                ClientId=self.client_id, AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": f"{ROLE_USERNAMES[role]}@{self.domain}", "PASSWORD": self.password},
            )
            self._tokens[role] = res["AuthenticationResult"]["AccessToken"]
        return self._tokens[role]

    def sub(self, role: str) -> str:
        return _sub(self.token(role))
