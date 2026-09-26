import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from study_archive_prep.local_model import (
    GenerationCancelled,
    LlamaCliRunner,
    ModelDownloadCancelled,
    ModelError,
    ModelSpec,
    ModelStore,
    ModelInstall,
)


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.payload = (b"model-fixture-" * 190_000)[:2_500_000]
        self.server = None
        self.thread = None

    def tearDown(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        self.temp.cleanup()

    def server_for(self, payload=None, ignore_range=False):
        data = payload if payload is not None else self.payload

        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                start = 0
                range_header = handler.headers.get("Range")
                if range_header and not ignore_range:
                    start = int(range_header.removeprefix("bytes=").removesuffix("-"))
                    handler.send_response(206)
                    handler.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
                else:
                    handler.send_response(200)
                handler.send_header("Content-Length", str(len(data) - start))
                handler.send_header("Accept-Ranges", "bytes")
                handler.end_headers()
                try:
                    for offset in range(start, len(data), 65536):
                        handler.wfile.write(data[offset:offset + 65536])
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/model.gguf"

    def spec_for(self, url):
        return ModelSpec("fixture/model", "deadbeef", "tiny.gguf", len(self.payload),
                         hashlib.sha256(self.payload).hexdigest(), "Apache-2.0")

    def test_download_verifies_checksum_and_writes_private_metadata(self):
        url = self.server_for()
        spec = self.spec_for(url)
        store = ModelStore(self.base / "private", spec)
        events = []
        result = store.download(progress=lambda current, total: events.append((current, total)),
                                source_url=url)
        self.assertEqual(Path(result.model_path).read_bytes(), self.payload)
        self.assertEqual(store.installed(verify=True), result)
        self.assertFalse(store.partial_path.exists())
        self.assertEqual(store.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(store.model_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(store.metadata_path.stat().st_mode & 0o777, 0o600)
        metadata = json.loads(store.metadata_path.read_text())
        self.assertEqual(metadata["revision"], "deadbeef")
        self.assertEqual(metadata["sha256"], spec.sha256)
        self.assertTrue(events)

    def test_interrupted_download_keeps_partial_and_resumes_from_range(self):
        url = self.server_for()
        spec = self.spec_for(url)
        store = ModelStore(self.base / "private", spec)
        seen = []

        def cancel_after_chunk(current, _total):
            seen.append(current)

        def cancelled():
            return bool(seen)

        with self.assertRaises(ModelDownloadCancelled):
            store.download(cancelled=cancelled, progress=cancel_after_chunk, source_url=url)
        part_size = store.partial_path.stat().st_size
        self.assertGreater(part_size, 0)
        self.assertLess(part_size, spec.size)
        self.assertFalse(store.model_path.exists())
        # Restart the server in the same port with the same deterministic payload.
        store.download(source_url=url)
        self.assertEqual(hashlib.sha256(store.model_path.read_bytes()).hexdigest(), spec.sha256)
        self.assertFalse(store.partial_path.exists())

    def test_server_that_ignores_range_restarts_instead_of_corrupting_file(self):
        url = self.server_for(ignore_range=True)
        spec = self.spec_for(url)
        store = ModelStore(self.base / "private", spec)
        store.directory.mkdir(parents=True)
        store.partial_path.write_bytes(b"stale prefix")
        result = store.download(source_url=url)
        self.assertEqual(Path(result.model_path).read_bytes(), self.payload)

    def test_checksum_mismatch_discards_partial_and_never_installs_model(self):
        url = self.server_for(payload=b"wrong model")
        wrong = ModelSpec("fixture/model", url, "tiny.gguf", len(b"wrong model"), "0" * 64,
                          "Apache-2.0")
        store = ModelStore(self.base / "private", wrong)
        with self.assertRaisesRegex(ModelError, "checksum did not match"):
            store.download(source_url=url)
        self.assertFalse(store.model_path.exists())
        self.assertFalse(store.partial_path.exists())

    def test_existing_corrupted_model_is_never_used_or_overwritten(self):
        url = self.server_for()
        spec = self.spec_for(url)
        store = ModelStore(self.base / "private", spec)
        store.directory.mkdir(parents=True)
        store.model_path.write_bytes(b"bad")
        with self.assertRaisesRegex(ModelError, "wrong size"):
            store.download()
        self.assertEqual(store.model_path.read_bytes(), b"bad")

    def test_pinned_model_details_are_recorded_and_not_latest_aliases(self):
        from study_archive_prep.local_model import PINNED_MODEL, LLAMA_CPP_COMMIT
        self.assertEqual(PINNED_MODEL.revision, "bc640142c66e1fdd12af0bd68f40445458f3869b")
        self.assertEqual(PINNED_MODEL.size, 2_497_280_256)
        self.assertEqual(PINNED_MODEL.sha256,
                         "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5")
        self.assertEqual(LLAMA_CPP_COMMIT, "7fe450e19305b828c199d602c23a8337aaa1f03b")


class LocalInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.model_path = self.base / "tiny.gguf"
        self.model_bytes = b"synthetic test model placeholder"
        self.model_path.write_bytes(self.model_bytes)
        self.model = ModelInstall(str(self.model_path), "fixture/model", "deadbeef", "tiny.gguf",
                                  len(self.model_bytes), hashlib.sha256(self.model_bytes).hexdigest(),
                                  "Apache-2.0")
        self.cli = self.base / "llama-cli"
        self.log = self.base / "arguments.json"
        self.sleep = False
        self._write_cli()

    def tearDown(self):
        self.temp.cleanup()

    def _write_cli(self):
        script = '''#!/usr/bin/env python3
import json, pathlib, sys, time
args = sys.argv[1:]
pathlib.Path("'''+str(self.log)+'''").write_text(json.dumps(args), encoding="utf-8")
prompt = pathlib.Path(args[args.index("--file") + 1]).read_text(encoding="utf-8")
if "--sleep" in args:
    time.sleep(5)
print("Предложенное название: Практическая часть")
'''
        if self.sleep:
            script = script.replace('args = sys.argv[1:]', 'args = sys.argv[1:] + ["--sleep"]')
        self.cli.write_text(script)
        self.cli.chmod(0o755)

    def runner(self):
        return LlamaCliRunner(self.cli, self.model, prompt_directory=self.base / "private-prompts")

    def test_generation_uses_private_prompt_file_and_returns_local_result(self):
        runner = self.runner()
        result = runner.generate("SRT text that stays local")
        self.assertEqual(result.text, "Предложенное название: Практическая часть")
        self.assertEqual(result.model_revision, "7fe450e19305b828c199d602c23a8337aaa1f03b")
        args = json.loads(self.log.read_text())
        self.assertIn("--model", args)
        self.assertIn("--no-display-prompt", args)
        prompt_path = Path(args[args.index("--file") + 1])
        self.assertFalse(prompt_path.exists())
        self.assertEqual(list((self.base / "private-prompts").glob(".local-model-prompt-*")), [])

    def test_cancellation_stops_local_process_and_cleans_prompt(self):
        self.sleep = True
        self._write_cli()
        with self.assertRaises(GenerationCancelled):
            self.runner().generate("local transcript", cancelled=lambda: True)
        self.assertEqual(list((self.base / "private-prompts").glob(".local-model-prompt-*")), [])

    def test_invalid_prompt_and_token_limits_are_rejected(self):
        runner = self.runner()
        with self.assertRaises(ValueError):
            runner.generate("   ")
        with self.assertRaises(ValueError):
            runner.generate("small", max_tokens=600)


if __name__ == "__main__":
    unittest.main()
