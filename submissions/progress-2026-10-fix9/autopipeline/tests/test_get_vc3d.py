"""scripts/get_vc3d.py (released as AutoPipeline's scripts/get_vc3d.py): finds the AppImage villa's release holds
now, checks it against GitHub's sha256, tries again while villa replaces the release, and fails with a reason.
A local server stands in for GitHub."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# scripts/get_vc3d.py in the release; the development copy may sit elsewhere, so both places are tried.
SCRIPT = next(p for p in (ROOT / "scripts" / "get_vc3d.py", ROOT / "scripts" / "release" / "autopipeline-files" /
                          "get_vc3d.py") if p.is_file())
spec = importlib.util.spec_from_file_location("get_vc3d", SCRIPT)
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

BODY = b"\x7fELF fake AppImage"
NAME = "VC3D-5432721-2026-10-14-linux-x86_64.AppImage"
SHA = hashlib.sha256(BODY).hexdigest()


def release(base, digest="sha256:" + SHA, appimages=(NAME,), dl="dl"):
    names = ["VC3D-5432721-2026-10-14-win64.exe", "VC3D-5432721-2026-10-14-win64.zip",
             "VC3D-5432721-2026-10-14-macos-arm64.dmg", *appimages, "VC3D-5432721-2026-10-14-linux-x86_64-debug.tar.zst"]
    return {"tag_name": "latest", "assets": [
        {"name": n, "browser_download_url": f"{base}/{dl}/{n}", **({"digest": digest} if n in appimages else
                                                                   {"digest": "sha256:" + "0" * 64})} for n in names]}


class Server:
    """GitHub's API and downloads. missing_first: how many lookups of `latest` answer 404 first, as while villa
    uploads a new release."""

    def __init__(self):
        self.downloads, self.lookups, self.seen_auth, self.missing_first = 0, 0, [], 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.seen_auth.append(self.headers.get("Authorization"))
                base = f"http://127.0.0.1:{self.server.server_port}"
                tag = self.path.rsplit("/", 1)[-1]
                if self.path.startswith("/dl/"):
                    outer.downloads += 1
                    return self.reply(200, BODY)
                if self.path.startswith("/short/"):   # declares more bytes than it sends, then closes
                    outer.downloads += 1
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(BODY) * 100))
                    self.end_headers()
                    self.wfile.write(BODY)
                    self.close_connection = True
                    return
                outer.lookups += 1
                answers = {"latest": release(base), "nodigest": release(base, digest=None),
                           "baddigest": release(base, digest="sha256:" + "f" * 64),
                           "two": release(base, appimages=(NAME, NAME.replace("5432721", "1111111"))),
                           "short": release(base, digest=None, dl="short")}
                if tag == "latest" and outer.lookups <= outer.missing_first:
                    return self.reply(404, b'{"message": "Not Found"}')
                if tag in ("limited", "denied"):
                    return self.reply(403 if tag == "limited" else 401, b'{"message": "no"}')
                if tag == "broken":
                    return self.reply(502, b"bad gateway")
                if tag not in answers:
                    return self.reply(404, b'{"message": "Not Found"}')
                return self.reply(200, json.dumps(answers[tag]).encode())

            def reply(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        self.api = self.base + "/repos/ScrollPrize/villa/releases/tags/{tag}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class GetVC3DTest(unittest.TestCase):
    def setUp(self):
        self.srv = Server()
        self.addCleanup(self.srv.close)
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env.pop("GITHUB_TOKEN", None)
        for p in (unittest.mock.patch.dict(os.environ, env, clear=True),
                  unittest.mock.patch.object(G, "RETRY_DELAYS", (0, 0, 0))):
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = G.main([*args, "--out", self.d, "--api", self.srv.api])
        return code, out.getvalue(), err.getvalue()

    def test_picks_the_one_linux_appimage_and_its_published_sha256(self):
        name, url, sha = G.release_asset(release("https://x"))
        self.assertEqual((name, url, sha), (NAME, f"https://x/dl/{NAME}", SHA))
        self.assertIsNone(G.release_asset(release("https://x", digest=None))[2])

    def test_zero_or_two_appimages_is_an_error_naming_the_assets(self):
        for appimages in ((), (NAME, NAME.replace("5432721", "1111111"))):
            with self.assertRaises(G.FetchError) as e:
                G.release_asset(release("https://x", appimages=appimages))
            self.assertIn(f"found {len(appimages)}", str(e.exception))
            self.assertIn("win64.exe", str(e.exception))

    def test_downloads_checks_and_prints_only_the_path(self):
        rec_path = os.path.join(self.d, "rec.json")
        code, out, err = self.run_main("--record", rec_path)
        self.assertEqual(code, 0, err)
        path = os.path.join(self.d, NAME)
        self.assertEqual(out, path + "\n")
        self.assertEqual(Path(path).read_bytes(), BODY)
        self.assertTrue(os.access(path, os.X_OK))
        self.assertFalse(os.path.exists(path + ".part"))
        self.assertIn("matches the sha256 GitHub publishes", err)
        rec = json.loads(Path(rec_path).read_text())
        self.assertEqual((rec["release"], rec["sha256"], rec["checked_against"]), ("latest", SHA, "GitHub"))

    def test_a_good_file_already_there_is_kept(self):
        self.assertEqual(self.run_main()[0], 0)
        code, out, err = self.run_main()
        self.assertEqual((code, self.srv.downloads), (0, 1), err)
        self.assertIn("already there, kept", err)

    def test_a_wrong_sha256_keeps_nothing(self):
        code, out, err = self.run_main("baddigest")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("not the expected", err)
        self.assertEqual(os.listdir(self.d), [])
        self.assertEqual(self.srv.downloads, 1)   # a mismatch is not tried again

    def test_a_given_sha256_must_agree_with_githubs(self):
        code, _, err = self.run_main("latest", "--sha256", "a" * 64)
        self.assertEqual(code, 1)
        self.assertIn("is not the sha256 GitHub publishes", err)
        self.assertEqual(self.srv.downloads, 0)
        self.assertEqual(self.run_main("latest", "--sha256", SHA.upper())[0], 0)

    def test_no_published_sha256_downloads_but_says_unchecked_unless_one_is_required(self):
        code, out, err = self.run_main("nodigest")
        self.assertEqual(code, 0, err)
        self.assertIn("NOT checked", err)
        shutil.rmtree(self.d)
        code, out, err = self.run_main("nodigest", "--require-sha256")
        self.assertEqual((code, out, self.srv.downloads), (1, "", 1))
        self.assertIn("GitHub publishes none", err)

    def test_latest_missing_while_villa_replaces_it_is_tried_again(self):
        self.srv.missing_first = 2
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertEqual(err.count("trying again"), 2)
        self.assertEqual(out, os.path.join(self.d, NAME) + "\n")

    def test_latest_missing_for_good_gives_up_with_the_reason(self):
        self.srv.missing_first = 99
        code, out, err = self.run_main()
        self.assertEqual((code, out, self.srv.lookups), (1, "", 4))
        self.assertIn("uploads a new one on every build", err)
        self.assertIn("gave up after 4 tries", err)

    def test_another_missing_tag_is_not_tried_again(self):
        code, out, err = self.run_main("nightly")
        self.assertEqual((code, self.srv.lookups), (1, 1))
        self.assertIn("its releases are latest and stable", err)

    def test_rate_limit_and_a_refused_token_say_what_to_do(self):
        code, out, err = self.run_main("limited")
        self.assertEqual((code, self.srv.lookups), (1, 1))
        self.assertIn("GITHUB_TOKEN", err)
        self.assertIn("--secret id=github_token", err)
        with unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": "stale"}):
            code, out, err = self.run_main("denied")
        self.assertEqual(code, 1)
        self.assertIn("refused the GITHUB_TOKEN that is set", err)

    def test_a_server_error_is_tried_again(self):
        code, out, err = self.run_main("broken")
        self.assertEqual((code, self.srv.lookups), (1, 4))
        self.assertIn("answered 502", err)

    def test_a_download_cut_short_keeps_nothing(self):
        code, out, err = self.run_main("short")
        self.assertEqual((code, out, self.srv.downloads), (1, "", 4))
        self.assertIn("stopped after", err)
        self.assertEqual(os.listdir(self.d), [])

    def test_ctrl_c_mid_download_leaves_no_part_file(self):
        class Reader(io.BytesIO):
            headers = {}

            def read(self, n=-1):
                raise KeyboardInterrupt

        with unittest.mock.patch.object(G, "_open", lambda url, timeout=60: Reader()):
            with self.assertRaises(KeyboardInterrupt):
                G.download("https://x/" + NAME, os.path.join(self.d, NAME))
        self.assertEqual(os.listdir(self.d), [])

    def test_a_url_with_its_sha256(self):
        url = f"{self.srv.base}/dl/{NAME}"
        code, out, err = self.run_main(url, "--sha256", SHA)
        self.assertEqual(code, 0, err)
        self.assertIn("matches --sha256", err)
        # The copy there does not match, so it downloads again, refuses the bytes and leaves that copy alone.
        code, out, err = self.run_main(url, "--sha256", "b" * 64)
        self.assertEqual((code, self.srv.downloads), (1, 2), err)
        self.assertEqual(sorted(os.listdir(self.d)), [NAME])

    def test_a_url_without_sha256_is_unchecked_or_refused_when_one_is_required(self):
        url = f"{self.srv.base}/dl/{NAME}"
        code, _, err = self.run_main(url)
        self.assertEqual(code, 0, err)
        self.assertIn("NOT checked", err)
        self.assertEqual(self.run_main(url, "--sha256", "xyz")[0], 1)
        code, _, err = self.run_main(url, "--require-sha256")
        self.assertEqual((code, self.srv.downloads), (1, 1))
        self.assertIn("pass the URL's sha256 too", err)

    def test_github_token_goes_only_to_the_api(self):
        with unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t0ken"}):
            self.assertEqual(self.run_main()[0], 0)   # neither the fake API nor the download is api.github.com
            seen = []
            with unittest.mock.patch.object(G.urllib.request, "urlopen", lambda req, timeout: seen.append(req)):
                G._open("https://api.github.com/repos/ScrollPrize/villa/releases/tags/latest")
                G._open(f"https://github.com/ScrollPrize/villa/releases/download/latest/{NAME}")
        self.assertEqual(set(self.srv.seen_auth), {None})
        self.assertEqual([r.get_header("Authorization") for r in seen], ["Bearer t0ken", None])
        # unredirected: urllib does not copy it onto a redirect
        self.assertEqual(list(seen[0].header_items()).count(("Authorization", "Bearer t0ken")), 1)
        self.assertNotIn("Authorization", seen[0].headers)


if __name__ == "__main__":
    unittest.main()
