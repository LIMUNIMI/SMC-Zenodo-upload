import os
import unittest
from unittest import mock

import requests

from tests.support import FakeResponse, WorkspaceTestCase
from zenodo_upload import zenodo
from zenodo_upload.zenodo import ZenodoClient


class RetryTestCase(WorkspaceTestCase):
    """ZenodoClient with a scripted session; the waits are recorded in ``self.sleeps``."""

    def client(self, get=(), post=()):
        self.session = mock.Mock(headers={})
        self.session.get.side_effect = list(get)
        self.session.post.side_effect = list(post)
        with mock.patch('requests.Session', return_value=self.session):
            return ZenodoClient('sandbox', 'https://sandbox.example', 'tok')


class TestGetRetries(RetryTestCase):
    def test_transient_status_is_retried_with_growing_waits(self):
        client = self.client(get=[FakeResponse(503), FakeResponse(500), FakeResponse(200, {})])

        response = client.get(1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.session.get.call_count, 3)
        self.assertEqual(self.sleeps, [2, 4])

    def test_429_is_retried(self):
        client = self.client(get=[FakeResponse(429), FakeResponse(200, [])])

        self.assertEqual(client.list_files(1).status_code, 200)

    def test_retry_after_is_honoured_up_to_a_limit(self):
        client = self.client(get=[
            FakeResponse(429, headers={'Retry-After': '7'}),
            FakeResponse(429, headers={'Retry-After': '99999'}),
            FakeResponse(200, {}),
        ])

        client.get(1)

        self.assertEqual(self.sleeps, [7, zenodo.MAX_RETRY_AFTER])

    def test_last_response_is_returned_when_attempts_run_out(self):
        client = self.client(get=[FakeResponse(503)] * zenodo.ATTEMPTS)

        response = client.get(1)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.session.get.call_count, zenodo.ATTEMPTS)
        self.assertEqual(len(self.sleeps), zenodo.ATTEMPTS - 1)

    def test_client_errors_are_not_retried(self):
        client = self.client(get=[FakeResponse(404)])

        self.assertEqual(client.get(1).status_code, 404)
        self.assertEqual(self.sleeps, [])

    def test_network_error_is_retried_then_raised(self):
        client = self.client(get=[requests.ConnectionError('down'), FakeResponse(200, {})])
        self.assertEqual(client.get(1).status_code, 200)

        client = self.client(get=[requests.Timeout('slow')] * zenodo.ATTEMPTS)
        with self.assertRaises(requests.Timeout):
            client.get(1)
        self.assertEqual(self.session.get.call_count, zenodo.ATTEMPTS)

    def test_every_request_has_a_timeout(self):
        client = self.client(get=[FakeResponse(200, {})])

        client.get(1)

        self.assertEqual(self.session.get.call_args.kwargs['timeout'], zenodo.TIMEOUT)


class TestPostRetries(RetryTestCase):
    def test_server_error_is_not_retried(self):
        # The request may have been processed: repeating it could duplicate it.
        for call in (
            lambda c: c.create({}), lambda c: c.publish(1),
        ):
            with self.subTest():
                client = self.client(post=[FakeResponse(503), FakeResponse(201, {})])

                self.assertEqual(call(client).status_code, 503)
                self.assertEqual(self.session.post.call_count, 1)

    def test_429_is_retried(self):
        client = self.client(post=[FakeResponse(429), FakeResponse(201, {'id': 1})])

        self.assertEqual(client.create({}).status_code, 201)
        self.assertEqual(self.sleeps, [2])

    def test_network_error_is_raised_at_once(self):
        client = self.client(post=[requests.ConnectionError('down')])

        with self.assertRaises(requests.ConnectionError):
            client.publish(1)

    def test_upload_sends_the_whole_file_again_after_a_429(self):
        path = os.path.abspath('some.pdf')
        with open(path, 'wb') as f:
            f.write(b'%PDF-1.4 content')
        sent = []

        def post(url, files, **kwargs):
            sent.append(files['file'].read())
            return FakeResponse(429) if len(sent) == 1 else FakeResponse(201, {})

        client = self.client()
        self.session.post.side_effect = post

        self.assertEqual(client.upload_file(1, 'some.pdf', path).status_code, 201)
        self.assertEqual(sent, [b'%PDF-1.4 content'] * 2)


if __name__ == '__main__':
    unittest.main()
