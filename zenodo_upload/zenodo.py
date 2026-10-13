"""Thin client for the Zenodo deposit REST API.

Methods return the `requests.Response`; judging it (see `succeeded`) is up to the caller.
"""

import requests

SERVERS = {
    'production': ('https://zenodo.org', 'PUBLIC_TOKEN'),
    'sandbox': ('https://sandbox.zenodo.org', 'SANDBOX_TOKEN'),
}


def succeeded(response):
    return response.status_code <= 210


class ZenodoClient:
    def __init__(self, target, url, token):
        self.target = target  # 'production' or 'sandbox'
        self.url = url
        self.token = token

    @classmethod
    def for_target(cls, target, secrets):
        """Client for 'production' or 'sandbox'; `secrets` holds PUBLIC_TOKEN and SANDBOX_TOKEN."""
        url, token_name = SERVERS[target]
        return cls(target, url, secrets[token_name])

    @property
    def _auth(self):
        return {'access_token': self.token}

    @property
    def _depositions(self):
        return f"{self.url}/api/deposit/depositions"

    def list_depositions(self):
        return requests.get(self._depositions, params=self._auth)

    def create(self, metadata):
        return requests.post(
            self._depositions,
            params=self._auth,
            json=metadata,
            headers={"Content-Type": "application/json"}
        )

    def get(self, deposition_id):
        return requests.get(f"{self._depositions}/{deposition_id}", params=self._auth)

    def list_files(self, deposition_id):
        return requests.get(f"{self._depositions}/{deposition_id}/files", params=self._auth)

    def upload_file(self, deposition_id, filename, path):
        url = f"{self._depositions}/{deposition_id}/files?access_token={self.token}"
        with open(path, 'rb') as f:
            return requests.post(url, data={'filename': filename}, files={'file': f})

    def publish(self, deposition_id):
        return requests.post(
            f"{self._depositions}/{deposition_id}/actions/publish", params=self._auth
        )

    def is_published(self, deposition_id):
        """True if Zenodo reports the deposition as already published."""
        response = self.get(deposition_id)
        try:
            return succeeded(response) and bool(response.json().get('submitted'))
        except ValueError:
            return False
