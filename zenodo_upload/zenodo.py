"""Thin client for the Zenodo deposit REST API.

Methods return the `requests.Response`; judging it (see `succeeded`) is up to the caller.
"""

import requests

SERVERS = {
    'production': ('https://zenodo.org', 'PUBLIC_TOKEN'),
    'sandbox': ('https://sandbox.zenodo.org', 'SANDBOX_TOKEN'),
}


class AccessError(Exception):
    """Zenodo refuses the token; the message says why."""


def succeeded(response):
    return response.status_code <= 210


class ZenodoClient:
    def __init__(self, target, url, token):
        self.target = target  # 'production' or 'sandbox'
        self.url = url
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bearer {token}'

    @classmethod
    def for_target(cls, target, secrets):
        """Client for 'production' or 'sandbox'; `secrets` holds PUBLIC_TOKEN and SANDBOX_TOKEN."""
        url, token_name = SERVERS[target]
        return cls(target, url, secrets[token_name])

    @property
    def _depositions(self):
        return f"{self.url}/api/deposit/depositions"

    def check_access(self):
        """Raise AccessError unless Zenodo accepts the token (lists the account's depositions)."""
        response = self.session.get(self._depositions)
        if not succeeded(response):
            raise AccessError(
                f"Cannot access {self.url}, HTTP {response.status_code}: check the token "
                f"for the {self.target} server in secrets.toml."
            )

    def create(self, metadata):
        return self.session.post(
            self._depositions,
            json=metadata,
            headers={"Content-Type": "application/json"}
        )

    def get(self, deposition_id):
        return self.session.get(f"{self._depositions}/{deposition_id}")

    def list_files(self, deposition_id):
        return self.session.get(f"{self._depositions}/{deposition_id}/files")

    def upload_file(self, deposition_id, filename, path):
        with open(path, 'rb') as f:
            return self.session.post(
                f"{self._depositions}/{deposition_id}/files",
                data={'filename': filename}, files={'file': f}
            )

    def publish(self, deposition_id):
        return self.session.post(f"{self._depositions}/{deposition_id}/actions/publish")

    def is_published(self, deposition_id):
        """True if Zenodo reports the deposition as already published."""
        response = self.get(deposition_id)
        try:
            return succeeded(response) and bool(response.json().get('submitted'))
        except ValueError:
            return False
