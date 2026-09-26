"""Pinned local model download, integrity verification, and offline inference."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

MODEL_REPOSITORY = "Qwen/Qwen3-4B-GGUF"
MODEL_REVISION = "bc640142c66e1fdd12af0bd68f40445458f3869b"
MODEL_FILENAME = "Qwen3-4B-Q4_K_M.gguf"
MODEL_SIZE = 2_497_280_256
MODEL_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
MODEL_LICENSE = "Apache-2.0"
LLAMA_CPP_RELEASE = "v0.5.0"
LLAMA_CPP_COMMIT = "7fe450e19305b828c199d602c23a8337aaa1f03b"
MODEL_CARD_URL = f"https://huggingface.co/{MODEL_REPOSITORY}/blob/{MODEL_REVISION}/README.md"
MODEL_LICENSE_URL = f"https://huggingface.co/{MODEL_REPOSITORY}/blob/{MODEL_REVISION}/LICENSE"


@dataclass(frozen=True)
class ModelSpec:
    repository: str
    revision: str
    filename: str
    size: int
    sha256: str
    license: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repository}/resolve/{self.revision}/{self.filename}"


PINNED_MODEL = ModelSpec(MODEL_REPOSITORY, MODEL_REVISION, MODEL_FILENAME,
                         MODEL_SIZE, MODEL_SHA256, MODEL_LICENSE)


class ModelError(RuntimeError):
    """A model download or local inference operation failed safely."""


class ModelDownloadCancelled(ModelError):
    """A model download was cancelled; the verified partial file can be resumed."""


class GenerationCancelled(ModelError):
    """Local model generation was stopped by the user."""


@dataclass(frozen=True)
class ModelInstall:
    model_path: str
    repository: str
    revision: str
    filename: str
    size: int
    sha256: str
    license: str


@dataclass(frozen=True)
class GenerationResult:
    text: str
    elapsed_seconds: float
    model_revision: str


def _hash_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    digest = hashlib.sha256()
    processed = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            processed += len(chunk)
            if progress is not None:
                progress(processed, path.stat().st_size)
    return digest.hexdigest()


def default_model_directory() -> Path:
    return Path.home() / "Library" / "Application Support" / "StudyArchivePrep" / "models" / "qwen3-4b-q4_k_m"


class ModelStore:
    def __init__(self, directory: str | Path | None = None,
                 spec: ModelSpec = PINNED_MODEL):
        self.directory = Path(directory or default_model_directory()).expanduser()
        self.spec = spec
        self.model_path = self.directory / spec.filename
        self.partial_path = self.directory / (spec.filename + ".part")
        self.metadata_path = self.directory / "model-install.json"

    def _prepare_directory(self) -> None:
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.directory.chmod(0o700)
            if self.directory.is_symlink() or not self.directory.is_dir():
                raise ModelError("The private model folder is not safe.")
        except OSError as exc:
            raise ModelError("Could not open the private model folder.") from exc

    def installed(self, *, verify: bool = True) -> ModelInstall | None:
        self._prepare_directory()
        if not self.model_path.exists():
            return None
        if self.model_path.is_symlink() or not self.model_path.is_file():
            raise ModelError("The saved model path is not a regular file.")
        if self.model_path.stat().st_size != self.spec.size:
            raise ModelError("The saved model has the wrong size and will not be used.")
        if verify and _hash_file(self.model_path) != self.spec.sha256:
            raise ModelError("The saved model checksum does not match; it will not be used.")
        self._write_metadata()
        return ModelInstall(str(self.model_path), self.spec.repository, self.spec.revision,
                            self.spec.filename, self.spec.size, self.spec.sha256, self.spec.license)

    def download(self, cancelled: Callable[[], bool] | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 opener=urllib.request.urlopen,
                 source_url: str | None = None) -> ModelInstall:
        self._prepare_directory()
        if self.model_path.exists():
            installed = self.installed(verify=True)
            if installed:
                return installed
        free = shutil.disk_usage(self.directory).free
        if free < self.spec.size + 128 * 1024 * 1024:
            raise ModelError("There is not enough free space for the model and a safe download.")
        try:
            part_size = self.partial_path.stat().st_size if self.partial_path.exists() else 0
            if self.partial_path.is_symlink() or (self.partial_path.exists() and not self.partial_path.is_file()):
                raise ModelError("The partial model path is not a regular file.")
            if part_size > self.spec.size:
                self.partial_path.unlink()
                part_size = 0
            digest = hashlib.sha256()
            current = 0
            if part_size:
                with self.partial_path.open("rb") as partial:
                    while chunk := partial.read(1024 * 1024):
                        digest.update(chunk)
                        current += len(chunk)
            headers = {"User-Agent": "StudyArchivePrep/0.1.0", "Accept-Encoding": "identity"}
            if current:
                headers["Range"] = f"bytes={current}-"
            request = urllib.request.Request(source_url or self.spec.url, headers=headers)
            try:
                response = opener(request, timeout=60)
            except TypeError:
                response = opener(request)
            with response:
                status = getattr(response, "status", response.getcode())
                if current and status != 206:
                    # Server ignored the resume range: restart from byte zero.
                    current = 0
                    digest = hashlib.sha256()
                    mode = "wb"
                elif current and status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {current}-"):
                        raise ModelError("The server returned a mismatched resume range.")
                    mode = "ab"
                elif not current and status in {200, 206}:
                    if status == 206 and not response.headers.get("Content-Range", "").startswith("bytes 0-"):
                        raise ModelError("The server returned an unexpected partial model range.")
                    mode = "wb"
                else:
                    raise ModelError(f"The model server returned HTTP {status}.")
                with self.partial_path.open(mode) as destination:
                    os.chmod(self.partial_path, 0o600)
                    while chunk := response.read(1024 * 1024):
                        if cancelled is not None and cancelled():
                            destination.flush()
                            os.fsync(destination.fileno())
                            raise ModelDownloadCancelled("Download cancelled. You can resume it later.")
                        destination.write(chunk)
                        digest.update(chunk)
                        current += len(chunk)
                        if progress is not None:
                            progress(current, self.spec.size)
                    destination.flush()
                    os.fsync(destination.fileno())
        except ModelDownloadCancelled:
            raise
        except ModelError:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise ModelError("The model download failed. Its partial file can be resumed.") from exc

        if current != self.spec.size:
            raise ModelError(f"The model download is incomplete ({current} of {self.spec.size} bytes).")
        actual_digest = digest.hexdigest()
        if actual_digest != self.spec.sha256:
            try:
                self.partial_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ModelError("The downloaded model checksum did not match; it was discarded.")
        if self.model_path.exists() or self.model_path.is_symlink():
            raise ModelError("A model file appeared during download; it was not overwritten.")
        try:
            os.link(self.partial_path, self.model_path)
            self.partial_path.unlink()
            os.chmod(self.model_path, 0o600)
            self._write_metadata()
        except FileExistsError as exc:
            raise ModelError("A model file appeared during download; it was not overwritten.") from exc
        except OSError as exc:
            raise ModelError("The verified model could not be installed safely.") from exc
        return ModelInstall(str(self.model_path), self.spec.repository, self.spec.revision,
                            self.spec.filename, self.spec.size, self.spec.sha256, self.spec.license)

    def _write_metadata(self) -> None:
        self._prepare_directory()
        payload = {
            "repository": self.spec.repository,
            "revision": self.spec.revision,
            "filename": self.spec.filename,
            "size": self.spec.size,
            "sha256": self.spec.sha256,
            "license": self.spec.license,
            "model_card_url": MODEL_CARD_URL,
            "license_url": MODEL_LICENSE_URL,
            "llama_cpp_release": LLAMA_CPP_RELEASE,
            "llama_cpp_commit": LLAMA_CPP_COMMIT,
            "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        fd, name = tempfile.mkstemp(prefix=".model-install-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.metadata_path)
            os.chmod(self.metadata_path, 0o600)
        finally:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass


class LlamaCliRunner:
    """Run a local llama.cpp CLI process; never calls a remote inference API."""

    def __init__(self, executable: str | Path, model: ModelInstall,
                 model_revision: str = LLAMA_CPP_COMMIT,
                 prompt_directory: str | Path | None = None):
        self.executable = Path(executable).expanduser().resolve(strict=False)
        spec = ModelSpec(model.repository, model.revision, model.filename,
                         model.size, model.sha256, model.license)
        verified = ModelStore(Path(model.model_path).parent, spec).installed(verify=True)
        if verified is None or verified.model_path != str(Path(model.model_path)):
            raise ModelError("The local model could not be verified before use.")
        self.model = verified
        self.model_revision = model_revision
        self.prompt_directory = Path(prompt_directory or Path(model.model_path).parent).expanduser()
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            raise ModelError("The bundled local model engine is unavailable.")

    def generate(self, prompt: str, *, max_tokens: int = 80,
                 timeout_seconds: int = 300,
                 cancelled: Callable[[], bool] | None = None) -> GenerationResult:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100_000:
            raise ValueError("prompt must contain 1 to 100,000 characters")
        if not 1 <= max_tokens <= 512:
            raise ValueError("max_tokens must be between 1 and 512")
        self.prompt_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix=".local-model-prompt-", suffix=".txt",
                                        dir=self.prompt_directory)
        prompt_path = Path(filename)
        started = time.monotonic()
        process = None
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(prompt)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(prompt_path, 0o600)
            command = [str(self.executable), "--model", self.model.model_path,
                       "--file", str(prompt_path), "--n-predict", str(max_tokens),
                       "--ctx-size", "4096", "--temp", "0.1", "--seed", "0",
                       "--single-turn", "--simple-io", "--no-display-prompt",
                       "--no-show-timings", "--no-warmup"]
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                try:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                               stdout=stdout_file, stderr=stderr_file,
                                               close_fds=True)
                except OSError as exc:
                    raise ModelError("The local model engine could not be started.") from exc
                deadline = time.monotonic() + timeout_seconds
                while process.poll() is None:
                    if cancelled is not None and cancelled():
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise GenerationCancelled("Local title generation was cancelled.")
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.wait()
                        raise ModelError("Local title generation timed out.")
                    time.sleep(0.1)
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read().decode("utf-8", errors="replace")
                stderr = stderr_file.read().decode("utf-8", errors="replace")
            if process.returncode != 0:
                detail = (stderr or "").strip()[-1200:]
                raise ModelError("The local model could not generate a suggestion." +
                                 (f" {detail}" if detail else ""))
            text = (stdout or "").strip()
            if not text:
                raise ModelError("The local model returned an empty suggestion.")
            return GenerationResult(text, time.monotonic() - started, self.model_revision)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            try:
                prompt_path.unlink(missing_ok=True)
            except OSError:
                pass
