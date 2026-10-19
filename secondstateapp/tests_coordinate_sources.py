"""Public research boundary tests; no outbound network is used."""

from email.message import Message
from io import BytesIO
import socket
import threading
import time
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import coordinate_sources as sources


PUBLIC_ADDRESS = (socket.AF_INET, ("93.184.216.34", 443))


class Response:
    def __init__(self, body=b"<title>Lot 17</title><main>Paper size: 10 x 12 inches.</main>",
                 status=200, headers=None):
        self.status = status
        self.headers = Message()
        for key, value in (headers or {"Content-Type": "text/html; charset=utf-8"}).items():
            self.headers[key] = value
        self.body = BytesIO(body)

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.body.read(size)

    def close(self):
        self.body.close()


def address_record(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


class CoordinateSourceTests(TestCase):
    def test_only_staff_links_latest_first_deduplicated_and_bounded(self):
        messages = [
            {"role": "staff", "body": "earlier https://example.com/old"},
            {"role": "assistant", "body": "ignore https://unrequested.example"},
            {"role": "staff", "body": "[lot](https://example.com/lot?id=Exact_ID) " +
             " ".join(f"https://example.com/{i}" for i in range(10))},
        ]
        result = sources.staff_urls(messages)
        self.assertEqual(len(result), 8)
        self.assertEqual(result[0], "https://example.com/lot?id=Exact_ID")
        self.assertNotIn("https://unrequested.example", result)
        self.assertEqual(sources.staff_urls([
            {"role": "staff", "body": "https://example.com/a https://example.com/a"}
        ]), ["https://example.com/a"])

    def test_unsafe_url_forms_never_resolve_or_connect(self):
        urls = ["http://example.com/lot", "https://user:password@example.com/lot",
                "https://example.com:8443/lot", "https://example.com\\@127.0.0.1/",
                "https://example.com/\r\nInjected: header", "https://[fe80::1%25eth0]/"]
        with patch.object(sources, "_resolve_public") as resolve:
            for url in urls:
                with self.subTest(url=url):
                    record = sources.fetch_source(url, time.monotonic() + 20)
                    self.assertTrue(record["error"])
                    self.assertFalse(record["text"])
        resolve.assert_not_called()

    def test_artifacts_preserve_safe_http_failure_and_drop_unrepresentable_urls(self):
        message = {"role": "staff", "body": "\n".join([
            "http://auction.example:80/lot", "https://user:password@auction.example/lot",
            "https://auction.example:8443/lot", "http://auction.example:8080/lot",
            "https://auction.example\\@127.0.0.1/", "https://[fe80::1%25eth0]/",
        ])}
        with patch.object(sources, "_resolve_public") as resolve:
            records = sources.research_messages([message])
        resolve.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_url"], "http://auction.example:80/lot")
        self.assertEqual(records[0]["final_url"], "http://auction.example:80/lot")
        self.assertIn("HTTPS", records[0]["error"])
        self.assertEqual(records[0]["text"], "")

    def test_private_reserved_mapped_and_mixed_dns_records_are_rejected(self):
        addresses = ["127.0.0.1", "10.1.2.3", "172.16.1.2", "192.168.1.2", "169.254.169.254",
                     "100.64.0.1", "192.0.2.1", "224.0.0.1", "0.0.0.0", "::1", "fc00::1",
                     "fe80::1", "2001:db8::1", "::ffff:127.0.0.1", "::ffff:93.184.216.34"]
        for address in addresses:
            for answers in ([address_record(address)], [address_record("93.184.216.34"), address_record(address)]):
                with self.subTest(address=address, mixed=len(answers) == 2), patch.object(
                    sources.socket, "getaddrinfo", return_value=answers,
                ), self.assertRaises(sources.SourceError):
                    sources._resolve_public("auction.example", time.monotonic() + 10)

    def test_connection_uses_validated_numeric_ip_and_original_tls_hostname(self):
        raw = Mock()
        secured = Mock()
        context = Mock()
        context.wrap_socket.return_value = secured
        with patch.object(sources.ssl, "create_default_context", return_value=context), patch.object(
            sources.socket, "socket", return_value=raw,
        ), patch.object(sources.socket, "getaddrinfo") as resolver:
            connection = sources.PinnedHTTPSConnection("auction.example", PUBLIC_ADDRESS, time.monotonic() + 10)
            connection.connect()
            raw.connect.assert_called_once_with(("93.184.216.34", 443))
            context.wrap_socket.assert_called_once_with(
                raw, server_hostname="auction.example", do_handshake_on_connect=False,
            )
            secured.do_handshake.assert_called_once()
            resolver.assert_not_called()
            connection.close()
            secured.close.assert_not_called()  # Header lifecycle cannot detach watchdog's transport.
            connection.finish()
            secured.close.assert_called_once()

    def test_redirect_to_private_destination_is_revalidated_before_connection(self):
        connection = Mock()
        connection.getresponse.return_value = Response(status=302, headers={"Location": "https://127.0.0.1/private"})

        def dns(host, port, **kwargs):
            return [address_record("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34")]

        with patch.object(sources.socket, "getaddrinfo", side_effect=dns), patch.object(
            sources, "PinnedHTTPSConnection", return_value=connection,
        ) as factory:
            record = sources.fetch_source("https://auction.example/lot", time.monotonic() + 20)
        self.assertIn("non-public", record["error"])
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(record["final_url"], "https://auction.example/lot")

    def test_redirect_downgrade_and_loops_fail_with_bounded_work(self):
        with patch.object(sources, "_read_page", return_value={"redirect": "http://example.com"}) as read:
            record = sources.fetch_source("https://example.com", time.monotonic() + 20)
        self.assertIn("HTTPS", record["error"])
        self.assertEqual(read.call_count, 1)
        with patch.object(sources, "_read_page", return_value={"redirect": "https://example.com"}) as read:
            record = sources.fetch_source("https://example.com", time.monotonic() + 20)
        self.assertIn("redirect limit", record["error"])
        self.assertEqual(read.call_count, sources.MAX_REDIRECTS + 1)

    def test_fetch_has_no_cookies_authorization_or_proxy_and_strips_active_content(self):
        body = b"<title>Lot &amp; notes</title><script>steal secrets</script><style>hidden</style><main>Lot 17 <b>print</b>. <a href='/'>contact@example.com</a></main>"
        connection = Mock(expired=False, sock=None)
        connection.getresponse.return_value = Response(body=body)
        with patch.object(sources, "_resolve_public", return_value=PUBLIC_ADDRESS), patch.object(
            sources, "PinnedHTTPSConnection", return_value=connection,
        ):
            record = sources.fetch_source("https://auction.example/lot?ID=ExactCase", time.monotonic() + 10)
        self.assertEqual(record["error"], "")
        self.assertEqual(record["source_url"], "https://auction.example/lot?ID=ExactCase")
        self.assertEqual(record["title"], "Lot & notes")
        self.assertIn("Lot 17 print", record["text"])
        self.assertNotIn("steal secrets", record["text"])
        headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual(set(headers), {"User-Agent", "Accept", "Accept-Encoding", "Connection"})
        self.assertEqual(headers["Accept-Encoding"], "identity")

    def test_declared_and_streamed_oversized_bodies_are_rejected(self):
        responses = [
            Response(headers={"Content-Type": "text/html", "Content-Length": str(sources.MAX_BYTES + 1)}),
            Response(body=b"x" * (sources.MAX_BYTES + 1)),
        ]
        for response in responses:
            connection = Mock(expired=False, sock=None)
            connection.getresponse.return_value = response
            with self.subTest(response=response), patch.object(sources, "_resolve_public", return_value=PUBLIC_ADDRESS), patch.object(
                sources, "PinnedHTTPSConnection", return_value=connection,
            ):
                record = sources.fetch_source("https://auction.example/lot", time.monotonic() + 10)
            self.assertIn("size limit", record["error"])
            self.assertEqual(record["text"], "")

    def test_unsupported_content_and_compression_are_rejected(self):
        for headers in ({"Content-Type": "application/pdf"}, {"Content-Type": "text/html", "Content-Encoding": "gzip"}):
            connection = Mock(expired=False, sock=None)
            connection.getresponse.return_value = Response(headers=headers)
            with self.subTest(headers=headers), patch.object(sources, "_resolve_public", return_value=PUBLIC_ADDRESS), patch.object(
                sources, "PinnedHTTPSConnection", return_value=connection,
            ):
                record = sources.fetch_source("https://auction.example/lot", time.monotonic() + 10)
            self.assertTrue(record["error"])

    def test_absolute_watchdog_interrupts_slow_body_and_total_budget_stops_next_request(self):
        aborted = threading.Event()
        connection = Mock(expired=False, sock=None)
        connection.abort.side_effect = aborted.set
        response = Response()

        def slow_read(size):
            aborted.wait(timeout=1)
            return b""

        response.read1 = slow_read
        connection.getresponse.return_value = response
        with patch.object(sources, "_resolve_public", return_value=PUBLIC_ADDRESS), patch.object(
            sources, "PinnedHTTPSConnection", return_value=connection,
        ):
            started = time.monotonic()
            record = sources.fetch_source("https://auction.example/lot", started + 0.04)
        self.assertLess(time.monotonic() - started, 0.75)
        self.assertTrue(aborted.is_set())
        self.assertIn("budget", record["error"])
        with patch.object(sources, "_read_page") as read:
            record = sources.fetch_source("https://auction.example/next", time.monotonic() - 1)
        read.assert_not_called()
        self.assertIn("budget", record["error"])

    def test_dns_wait_is_bounded(self):
        release = threading.Event()

        def slow_dns(*args, **kwargs):
            release.wait(timeout=1)
            return [address_record("93.184.216.34")]

        try:
            with patch.object(sources.socket, "getaddrinfo", side_effect=slow_dns), self.assertRaisesRegex(
                sources.SourceError, "DNS lookup timed out",
            ):
                sources._resolve_public("auction.example", time.monotonic() + 0.03)
        finally:
            release.set()
