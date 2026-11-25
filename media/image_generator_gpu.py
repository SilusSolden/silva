from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from silva.config import CONFIG_DIR, load_config
from silva.logger import log_info

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "stabilityai/sd-turbo"
MIN_CAPABILITY = (7, 5)
ProgressCallback = Callable[[str], None] | None


def _as_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _as_float(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temp, path)


def _read_status(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def gpu_status() -> dict:
    result = {
        "torch": "",
        "cuda_build": "",
        "diffusers": "",
        "cuda_available": False,
        "device": "",
        "capability": [],
        "free_vram_gb": 0.0,
        "total_vram_gb": 0.0,
        "backend_supported": False,
        "error": "",
    }
    try:
        import torch
    except Exception as exc:
        result["error"] = f"PyTorch is not available: {exc}"
        return result
    result["torch"] = str(torch.__version__)
    result["cuda_build"] = str(torch.version.cuda or "")
    result["cuda_available"] = bool(torch.cuda.is_available())
    try:
        import diffusers

        result["diffusers"] = str(diffusers.__version__)
    except Exception as exc:
        result["error"] = f"Diffusers is not available: {exc}"
    if result["cuda_available"]:
        try:
            free, total = torch.cuda.mem_get_info()
            result["device"] = str(torch.cuda.get_device_name(0))
            result["capability"] = list(torch.cuda.get_device_capability(0))
            result["free_vram_gb"] = round(free / (1024**3), 2)
            result["total_vram_gb"] = round(total / (1024**3), 2)
        except Exception as exc:
            result["error"] = f"Could not read CUDA memory: {exc}"
    result["backend_supported"] = bool(
        result["cuda_available"] and result["diffusers"] and not result["error"]
    )
    return result


def resolve_gpu_settings(
    config: dict | None = None,
    *,
    test: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    cfg = config if config is not None else load_config()
    base_key = "image_generator_test_size" if test else "image_generator_gpu_size"
    base_default = 256 if test else 512
    base_limit = 512 if test else 768
    base = _as_int(cfg.get(base_key), base_default, 256, base_limit)
    target_width = _as_int(width, base, 256, 768)
    target_height = _as_int(height, base, 256, 768)
    target_width -= target_width % 8
    target_height -= target_height % 8
    steps_default = 1 if test else 4
    steps_limit = 4 if test else 30
    steps = _as_int(
        cfg.get("image_generator_test_steps" if test else "image_generator_steps"),
        steps_default,
        1,
        steps_limit,
    )
    guidance = 0.0 if test else _as_float(cfg.get("image_generator_guidance"), 0.0, 0.0, 20.0)
    timeout_key = "image_generator_test_timeout_seconds" if test else "image_generator_gpu_timeout_seconds"
    timeout_default = 600.0 if test else 180.0
    timeout = _as_float(cfg.get(timeout_key), timeout_default, 30.0, 1800.0)
    min_free = _as_float(cfg.get("image_generator_min_free_vram_gb"), 4.0, 1.0, 32.0)
    cache = str(cfg.get("image_generator_model_cache") or "").strip()
    return {
        "model": str(cfg.get("image_generator_model") or DEFAULT_MODEL),
        "width": target_width,
        "height": target_height,
        "steps": steps,
        "guidance": guidance,
        "strength": _as_float(cfg.get("image_generator_edit_strength"), 0.35, 0.05, 0.95),
        "min_free_vram_gb": min_free,
        "timeout": timeout,
        "cache_dir": cache,
        "allow_cpu": bool(cfg.get("image_generator_allow_cpu_model", False)),
        "device": "cuda",
        "test": bool(test),
    }


def gpu_refusal(status: dict, settings: dict, *, require_cuda: bool = True) -> str | None:
    if status.get("error") and not status.get("torch"):
        return "CUDA image generation is unavailable because PyTorch is not installed."
    if not status.get("torch"):
        return "CUDA image generation is unavailable because PyTorch is not installed."
    if not status.get("diffusers"):
        return "CUDA image generation is unavailable because diffusers is not installed."
    if not status.get("cuda_available"):
        if not require_cuda and settings.get("allow_cpu"):
            return None
        return "CUDA is not available, so I am not running the neural image model."
    if require_cuda and tuple(status.get("capability") or []) < MIN_CAPABILITY:
        return "This GPU is too old for the CUDA image model."
    free = float(status.get("free_vram_gb") or 0.0)
    if free < float(settings.get("min_free_vram_gb") or 0.0):
        return (
            f"Only {free:.1f}GB of video memory is free. "
            "Image Studio needs more headroom before it can safely generate."
        )
    return None


def _status_label(status: dict) -> str:
    stage = str(status.get("stage") or "")
    if stage == "loading":
        return "Loading the CUDA image model..."
    if stage == "generate":
        step = int(status.get("step") or 0)
        steps = int(status.get("steps") or 0)
        return f"Generating on the GPU... {step}/{steps}"
    if stage == "prepare":
        return "Downloading the CUDA image model..."
    if stage == "done":
        return "CUDA image finished."
    return "Starting CUDA image generation..."


def _run_worker(args: dict, timeout: float, progress: ProgressCallback = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="silva-gpu-") as folder:
        temporary = Path(folder)
        args_path = temporary / "args.json"
        status_path = temporary / "status.json"
        args["status_path"] = str(status_path)
        args_path.write_text(json.dumps(args), encoding="utf-8")
        command = [sys.executable, "-m", "silva.media.image_generator_gpu", "--worker", str(args_path)]
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        last_label = ""
        while process.poll() is None:
            current = _read_status(status_path)
            label = _status_label(current)
            if label and label != last_label:
                last_label = label
                log_info(f"Image Studio GPU: {label}")
                if progress is not None:
                    progress(label)
            if time.monotonic() >= deadline:
                process.kill()
                process.wait(timeout=5)
                return {"error": f"CUDA image generation timed out after {int(timeout)} seconds."}
            time.sleep(0.4)
        final = _read_status(status_path)
        if final.get("status") == "done":
            return {"ok": True, **final}
        error = str(final.get("error") or "")
        if not error:
            error = f"The CUDA image worker exited with code {process.returncode}."
        return {"error": error}


def render_gpu_image(
    prompt: str,
    *,
    out_path: Path,
    settings: dict,
    status: dict | None = None,
    seed: int | None = None,
    image_path: Path | str = "",
    progress: ProgressCallback = None,
) -> dict:
    current = status if status is not None else gpu_status()
    refusal = gpu_refusal(current, settings)
    if refusal:
        return {"error": refusal}
    chosen_seed = seed if seed is not None else int.from_bytes(os.urandom(4), "little")
    args = {
        "prompt": str(prompt or "").strip(),
        "out_path": str(out_path),
        "image_path": str(image_path or ""),
        "model": str(settings.get("model") or DEFAULT_MODEL),
        "width": int(settings.get("width") or 512),
        "height": int(settings.get("height") or 512),
        "steps": int(settings.get("steps") or 4),
        "guidance": float(settings.get("guidance") or 0.0),
        "strength": float(settings.get("strength") or 0.35),
        "seed": chosen_seed,
        "device": "cuda" if current.get("cuda_available") else "cpu",
        "cache_dir": str(settings.get("cache_dir") or ""),
    }
    return _run_worker(args, float(settings.get("timeout") or 180.0), progress)


def startup_check(config: dict | None = None) -> dict:
    cfg = config if config is not None else load_config()
    settings = resolve_gpu_settings(cfg, test=True)
    status = gpu_status()
    refusal = gpu_refusal(status, settings)
    return {
        "ready": refusal is None,
        "message": (
            f"CUDA image generation is ready on {status.get('device', 'the GPU')} "
            f"with {status.get('free_vram_gb', 0):.1f}GB free video memory."
            if refusal is None
            else f"CUDA image generation is not ready: {refusal}"
        ),
        "status": status,
        "settings": settings,
    }


def prepare_model(settings: dict | None = None) -> dict:
    cfg = load_config()
    chosen = settings if settings is not None else resolve_gpu_settings(cfg, test=True)
    status = gpu_status()
    if not status.get("torch"):
        return {"error": "PyTorch is not installed."}
    if not status.get("diffusers"):
        return {"error": "Diffusers is not installed."}
    args = {
        "prepare": True,
        "model": str(chosen.get("model") or DEFAULT_MODEL),
        "device": "cpu",
        "cache_dir": str(chosen.get("cache_dir") or ""),
    }
    return _run_worker(args, 900.0)


def run_test(config: dict | None = None) -> dict:
    cfg = config if config is not None else load_config()
    settings = resolve_gpu_settings(cfg, test=True)
    status = gpu_status()
    refusal = gpu_refusal(status, settings)
    if refusal:
        return {"ok": False, "message": refusal}
    store = CONFIG_DIR / "generated_images"
    store.mkdir(parents=True, exist_ok=True)
    out_path = store / f"gpu-test-{int(time.time())}.png"
    result = render_gpu_image(
        "a small friendly robot on a clean blue background",
        out_path=out_path,
        settings=settings,
        status=status,
        seed=42,
    )
    if result.get("error"):
        return {"ok": False, "message": str(result["error"])}
    return {
        "ok": True,
        "path": str(out_path),
        "message": f"CUDA test image saved to {out_path}",
        "device": status.get("device", ""),
        "free_vram_gb": status.get("free_vram_gb", 0.0),
    }


def _worker(args_path: str) -> int:
    status_path = Path("")
    try:
        args = json.loads(Path(args_path).read_text(encoding="utf-8"))
        status_path = Path(str(args.get("status_path") or ""))
        _write_status(status_path, {"status": "running", "stage": "starting"})
        import torch
        from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image

        device = str(args.get("device") or "cuda")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available in the worker.")
        torch.set_num_threads(2)
        torch.backends.cuda.matmul.allow_tf32 = True
        dtype = torch.float16 if device == "cuda" else torch.float32
        options = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "safety_checker": None,
        }
        cache_dir = str(args.get("cache_dir") or "").strip()
        if cache_dir:
            options["cache_dir"] = cache_dir
        model = str(args.get("model") or DEFAULT_MODEL)
        if args.get("prepare"):
            _write_status(status_path, {"status": "running", "stage": "prepare", "model": model})
            AutoPipelineForText2Image.from_pretrained(model, **options)
            _write_status(status_path, {"status": "done", "stage": "done", "model": model})
            return 0

        image_path = str(args.get("image_path") or "")
        source = None
        if image_path and Path(image_path).is_file():
            source = Image.open(image_path).convert("RGB")
        pipeline_class = AutoPipelineForImage2Image if source is not None else AutoPipelineForText2Image
        _write_status(status_path, {"status": "running", "stage": "loading", "model": model})
        pipe = pipeline_class.from_pretrained(model, **options)
        if hasattr(pipe, "enable_attention_slicing"):
            pipe.enable_attention_slicing("max")
        if hasattr(pipe, "enable_vae_slicing"):
            pipe.enable_vae_slicing()
        if hasattr(pipe, "enable_vae_tiling"):
            pipe.enable_vae_tiling()
        pipe = pipe.to(device)
        width = int(args.get("width") or 512)
        height = int(args.get("height") or 512)
        steps = int(args.get("steps") or 4)
        generator = (
            torch.Generator(device=device).manual_seed(int(args.get("seed") or 0))
            if device == "cuda"
            else torch.Generator().manual_seed(int(args.get("seed") or 0))
        )
        call = {
            "prompt": str(args.get("prompt") or ""),
            "num_inference_steps": steps,
            "guidance_scale": float(args.get("guidance") or 0.0),
            "generator": generator,
        }
        if source is not None:
            call["image"] = source.resize((width, height))
            call["strength"] = float(args.get("strength") or 0.35)
        else:
            call["width"] = width
            call["height"] = height
        signature = inspect.signature(pipe.__call__)
        if "callback_on_step_end" in signature.parameters:

            def callback_on_step_end(_pipe, step, _timestep, callback_kwargs):
                _write_status(
                    status_path,
                    {
                        "status": "running",
                        "stage": "generate",
                        "step": int(step) + 1,
                        "steps": steps,
                    },
                )
                return callback_kwargs

            call["callback_on_step_end"] = callback_on_step_end
        elif "callback" in signature.parameters:

            def callback(step, _timestep, _latents):
                _write_status(
                    status_path,
                    {
                        "status": "running",
                        "stage": "generate",
                        "step": int(step) + 1,
                        "steps": steps,
                    },
                )

            call["callback"] = callback
        _write_status(status_path, {"status": "running", "stage": "generate", "step": 0, "steps": steps})
        with torch.inference_mode():
            image = pipe(**call).images[0]
        out_path = Path(str(args.get("out_path") or ""))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(out_path)
        _write_status(
            status_path,
            {
                "status": "done",
                "stage": "done",
                "path": str(out_path),
                "device": device,
                "width": width,
                "height": height,
            },
        )
        del pipe
        if device == "cuda":
            torch.cuda.empty_cache()
        return 0
    except Exception as exc:
        if status_path:
            _write_status(
                status_path,
                {"status": "error", "stage": "error", "error": f"{type(exc).__name__}: {exc}"},
            )
        return 1


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "--worker":
        if len(values) < 2:
            print("Usage: python -m silva.media.image_generator_gpu --worker <args.json>")
            return 2
        return _worker(values[1])
    if values and values[0] == "status":
        print(json.dumps(gpu_status(), indent=2))
        return 0
    if values and values[0] in {"check", "startup"}:
        result = startup_check()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ready") else 1
    if values and values[0] == "prepare":
        result = prepare_model()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if values and values[0] == "test":
        result = run_test()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    print("Usage: python -m silva.media.image_generator_gpu {status|check|prepare|test}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
