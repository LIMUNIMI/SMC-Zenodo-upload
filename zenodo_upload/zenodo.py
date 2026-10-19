"""Thin client for the Zenodo deposit REST API.

Methods return the `requests.Response`; judging it (`response.ok`) is up to the caller.
Requests that fail for a transient reason are repeated, see `_retry`.
"""

import time

import requests

SERVERS = {
    'production': ('https://zenodo.org', 'PUBLIC_TOKEN'),
    'sandbox': ('https://sandbox.zenodo.org', 'SANDBOX_TOKEN'),
}


ATTEMPTS = 5  # per request, the first one included
BACKOFF_SECONDS = 2  # wait before the second attempt, doubled at each further one
MAX_RETRY_AFTER = 120  # longest wait asked by the server that is honoured, in seconds
TIMEOUT = (10, 300)  # connect and read timeouts, in seconds


class AccessError(Exception):
    """Zenodo refuses the token; the message says why."""


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
        if not response.ok:
            raise AccessError(
                f"Cannot access {self.url}, HTTP {response.status_code}: check the token "
                f"for the {self.target} server in secrets.toml."
            )

    def create(self, metadata):
        return self._retry('POST', lambda: self.session.post(
            self._depositions, json=metadata, timeout=TIMEOUT,
            headers={"Content-Type": "application/json"}
        ))

    def get(self, deposition_id):
        return self._retry('GET', lambda: self.session.get(
            f"{self._depositions}/{deposition_id}", timeout=TIMEOUT
        ))

    def list_files(self, deposition_id):
        return self._retry('GET', lambda: self.session.get(
            f"{self._depositions}/{deposition_id}/files", timeout=TIMEOUT
        ))

    def upload_file(self, deposition_id, filename, path):
        def send():  # the file is opened again at every attempt
            with open(path, 'rb') as f:
                return self.session.post(
                    f"{self._depositions}/{deposition_id}/files", timeout=TIMEOUT,
                    data={'filename': filename}, files={'file': f}
                )
        return self._retry('POST', send)

    def publish(self, deposition_id):
        return self._retry('POST', lambda: self.session.post(
            f"{self._depositions}/{deposition_id}/actions/publish", timeout=TIMEOUT
        ))

    def is_published(self, deposition_id):
        """True if Zenodo reports the deposition as already published."""
        response = self.get(deposition_id)
        try:
            return response.ok and bool(response.json().get('submitted'))
        except ValueError:
            return False

    def _retry(self, method, send):
        """
        Call `send()` up to ATTEMPTS times, waiting longer each time (or as long as the
        server's Retry-After asks). A GET is repeated on 429, on 5xx and on network errors;
        any other request only on 429, which says it was not processed: a POST that got a
        5xx may have worked, repeating it could duplicate a draft or a publication (the
        resume logic of the uploader copes with those cases).
        The last response is returned, or the last network error raised.
        """
        for attempt in range(1, ATTEMPTS + 1):
            last = attempt == ATTEMPTS
            try:
                response = send()
            except (requests.ConnectionError, requests.Timeout):
                if method != 'GET' or last:
                    raise
                time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
                continue
            transient = response.status_code == 429 or (
                method == 'GET' and response.status_code >= 500
            )
            if not transient or last:
                return response
            time.sleep(_wait_time(response, attempt))


def _wait_time(response, attempt):
    """Seconds to wait after a failed attempt: Retry-After if the server gave one."""
    backoff = BACKOFF_SECONDS * 2 ** (attempt - 1)
    try:
        return min(float(response.headers['Retry-After']), MAX_RETRY_AFTER)
    except (KeyError, ValueError):
        return backoff
