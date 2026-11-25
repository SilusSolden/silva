from __future__ import annotations

import json
import os
import random
import threading
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from silva.config import CONFIG_DIR, load_config
from silva.conversation.safety import apply_safety, sanitize_image_prompt
from silva.logger import log_info

STORE_DIR = CONFIG_DIR / "generated_images"
INDEX_FILE = STORE_DIR / "index.json"
ACTIVE_FILE = STORE_DIR / "active.json"
_job_lock = threading.Lock()
_active_jobs: set[str] = set()

PALETTES = {
    "ocean": ((8, 32, 64), (24, 116, 152), (126, 214, 223)),
    "forest": ((12, 42, 30), (38, 110, 70), (156, 204, 101)),
    "sunset": ((58, 16, 42), (196, 68, 62), (255, 196, 105)),
    "neon": ((12, 8, 34), (124, 32, 168), (80, 240, 220)),
    "paper": ((238, 235, 224), (198, 190, 170), (74, 66, 54)),
    "error": ((42, 8, 12), (156, 30, 42), (255, 138, 128)),
}
ASPECTS = {
    "square": (1.0, 1.0),
    "wide": (1.4, 1.0),
    "tall": (1.0, 1.4),
    "portrait": (0.8, 1.0),
}


def ensure_store() -> Path:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    return STORE_DIR


def _read_json(path: Path, fallback: dict) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return fallback


def _write_json(path: Path, data: dict) -> None:
    ensure_store()
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def load_index() -> list[dict]:
    data = _read_json(INDEX_FILE, {"records": []})
    records = data.get("records") or []
    return [record for record in records if isinstance(record, dict)]


def save_index(records: list[dict]) -> None:
    _write_json(INDEX_FILE, {"records": records})


def _load_active() -> dict[str, str]:
    data = _read_json(ACTIVE_FILE, {"active": {}})
    active = data.get("active") or {}
    return {str(key): str(value) for key, value in active.items() if value}


def _save_active(active: dict[str, str]) -> None:
    _write_json(ACTIVE_FILE, {"active": active})


def active_image_for(user_id: str = "") -> dict | None:
    image_id = _load_active().get(str(user_id or "default") or "default") or ""
    return get_generated_image(image_id)


def set_active_image(image_id: str, user_id: str = "") -> None:
    active = _load_active()
    active[str(user_id or "default") or "default"] = str(image_id)
    _save_active(active)


def get_generated_image(image_id: str) -> dict | None:
    return next(
        (record for record in load_index() if record.get("id") == str(image_id)),
        None,
    )


def recent_images(limit: int = 8) -> list[dict]:
    return load_index()[-max(1, int(limit)) :][::-1]


def _palette_name(prompt: str) -> str:
    text = prompt.lower()
    if any(word in text for word in ("error", "bug", "crash", "issue", "glitch")):
        return "error"
    if any(word in text for word in ("neon", "cyber", "glow", "futuristic", "space")):
        return "neon"
    if any(word in text for word in ("ocean", "water", "sea", "blue", "ice")):
        return "ocean"
    if any(word in text for word in ("forest", "tree", "nature", "green", "garden")):
        return "forest"
    if any(word in text for word in ("sunset", "fire", "warm", "orange", "red")):
        return "sunset"
    return "paper"


def _motifs(prompt: str) -> list[str]:
    text = prompt.lower()
    found: list[str] = []
    for motif, words in (
        ("chart", ("chart", "graph", "bar", "data", "statistics")),
        ("robot", ("robot", "ai", "assistant", "bot", "machine")),
        ("house", ("house", "home", "building", "room", "office")),
        ("tree", ("tree", "forest", "plant", "nature", "garden")),
        ("car", ("car", "vehicle", "truck", "road")),
        ("stars", ("star", "moon", "planet", "space", "night")),
        ("person", ("person", "face", "human", "people", "portrait")),
    ):
        if any(word in text for word in words):
            found.append(motif)
    return found or ["shapes"]


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _background(
    dimensions: tuple[int, int], palette: tuple[tuple[int, int, int], ...]
) -> Image.Image:
    width, height = dimensions
    image = Image.new("RGB", (width, height), palette[0])
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / max(1, height - 1)
        color = tuple(
            int(palette[0][channel] * (1 - blend) + palette[1][channel] * blend)
            for channel in range(3)
        )
        draw.line((0, y, width, y), fill=color)
    return image


def _draw_motif(draw: ImageDraw.ImageDraw, motif: str, box: tuple[int, int, int, int], accent) -> None:
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    if motif == "chart":
        base = bottom - 12
        for index in range(5):
            bar_height = int(height * (0.25 + 0.14 * index))
            x0 = left + 18 + index * (width - 40) // 5
            draw.rectangle((x0, base - bar_height, x0 + 28, base), fill=accent)
        draw.line((left + 8, base, right - 8, base), fill=(255, 255, 255), width=2)
    elif motif == "robot":
        draw.rounded_rectangle((left + 40, top + 40, right - 40, bottom - 60), radius=28, outline=accent, width=4)
        draw.ellipse((left + 76, top + 92, left + 110, top + 126), fill=accent)
        draw.ellipse((right - 110, top + 92, right - 76, top + 126), fill=accent)
        draw.line((left + 100, bottom - 60, right - 100, bottom - 60), fill=accent, width=3)
    elif motif == "house":
        draw.rectangle((left + 55, top + 110, right - 55, bottom - 30), outline=accent, width=4)
        draw.polygon(
            [(left + 35, top + 110), ((left + right) // 2, top + 35), (right - 35, top + 110)],
            outline=accent,
        )
        draw.rectangle((right // 2 - 18, bottom - 90, right // 2 + 18, bottom - 30), fill=accent)
    elif motif == "tree":
        draw.rectangle((left + width // 2 - 12, top + height // 2, left + width // 2 + 12, bottom - 30), fill=accent)
        draw.ellipse((left + 45, top + 35, right - 45, top + height // 2 + 30), outline=accent, width=4)
    elif motif == "car":
        draw.rounded_rectangle((left + 30, top + height // 2 - 10, right - 30, bottom - 55), radius=16, outline=accent, width=4)
        draw.ellipse((left + 60, bottom - 70, left + 110, bottom - 20), fill=accent)
        draw.ellipse((right - 110, bottom - 70, right - 60, bottom - 20), fill=accent)
    elif motif == "stars":
        for index in range(12):
            x = left + 30 + ((index * 71) % max(1, width - 60))
            y = top + 30 + ((index * 43) % max(1, height - 60))
            radius = 3 + (index % 3)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=accent)
        draw.arc((right - 130, top + 20, right - 30, top + 120), 20, 300, fill=accent, width=4)
    elif motif == "person":
        draw.ellipse((left + width // 2 - 55, top + 45, left + width // 2 + 55, top + 165), outline=accent, width=4)
        draw.arc((left + 45, top + 150, right - 45, bottom - 20), 180, 360, fill=accent, width=6)
    else:
        for index in range(4):
            inset = 30 + index * 26
            draw.rounded_rectangle(
                (left + inset, top + inset, right - inset, bottom - inset),
                radius=18,
                outline=accent,
                width=2,
            )


def _render_lightweight(
    prompt: str,
    previous: Path | None = None,
    *,
    style: str = "auto",
    aspect: str = "square",
    seed: int | None = None,
) -> Image.Image:
    config = load_config()
    base = max(256, min(1024, int(config.get("image_generator_max_size", 640) or 640)))
    ratio_x, ratio_y = ASPECTS.get(str(aspect or "square").lower(), ASPECTS["square"])
    divisor = max(ratio_x, ratio_y)
    width = max(256, int(base * ratio_x / divisor))
    height = max(256, int(base * ratio_y / divisor))
    style_name = str(style or "auto").lower()
    palette_name = style_name if style_name in PALETTES else _palette_name(prompt)
    palette = PALETTES[palette_name]
    image = (
        Image.open(previous).convert("RGB")
        if previous and previous.is_file()
        else _background((width, height), palette)
    )
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image, "RGBA")
    motifs = _motifs(prompt)
    rng = random.Random(seed)
    for index, motif in enumerate(motifs):
        inset = 40 + index * 22
        jitter = rng.randint(-8, 8)
        _draw_motif(
            draw,
            motif,
            (inset, inset + jitter, width - inset, height - inset - 34 + jitter),
            palette[2] + (210,),
        )
    label = prompt.strip()[:70] or "Silva concept"
    draw.rounded_rectangle(
        (24, height - 72, width - 24, height - 20), radius=12, fill=(0, 0, 0, 150)
    )
    draw.text((40, height - 60), label, font=_font(18), fill=(255, 255, 255, 255))
    return image


def _render(
    prompt: str,
    previous: Path | None = None,
    *,
    style: str = "auto",
    aspect: str = "square",
    seed: int | None = None,
    test: bool = False,
) -> tuple[Image.Image | None, dict, dict | None]:
    config = load_config()
    backend = str(config.get("image_generator_backend", "auto") or "auto").lower()
    wants_gpu = test or backend in {"auto", "gpu"}
    if wants_gpu:
        from silva.media.image_generator_gpu import (
            gpu_refusal,
            gpu_status,
            render_gpu_image,
            resolve_gpu_settings,
        )

        ratio_x, ratio_y = ASPECTS.get(str(aspect or "square").lower(), ASPECTS["square"])
        base = _as_gpu_base(config, test=test)
        divisor = max(ratio_x, ratio_y)
        width = max(256, int(base * ratio_x / divisor))
        height = max(256, int(base * ratio_y / divisor))
        settings = resolve_gpu_settings(config, test=test, width=width, height=height)
        status = gpu_status()
        refusal = gpu_refusal(status, settings)
        if refusal:
            if backend == "gpu" or test:
                return None, {"backend": "gpu", "error": refusal}, settings
            log_info(f"Image Studio using lightweight renderer: {refusal}")
        else:
            ensure_store()
            out_path = STORE_DIR / f"cuda-{uuid.uuid4().hex[:12]}.png"
            result = render_gpu_image(
                prompt,
                out_path=out_path,
                settings=settings,
                status=status,
                seed=seed,
                image_path=previous or "",
            )
            if result.get("error"):
                return None, {"backend": "gpu", "error": str(result["error"])}, settings
            image = Image.open(out_path).convert("RGB")
            return image, {"backend": "gpu", "device": status.get("device", "")}, settings
    image = _render_lightweight(prompt, previous, style=style, aspect=aspect, seed=seed)
    return image, {"backend": "lightweight", "device": ""}, {}


def _as_gpu_base(config: dict, *, test: bool) -> int:
    key = "image_generator_test_size" if test else "image_generator_gpu_size"
    default = 256 if test else 512
    limit = 512 if test else 768
    try:
        value = int(config.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return max(256, min(limit, value))


def generation_preflight() -> str | None:
    config = load_config()
    if not bool(config.get("image_generator_enabled", True)):
        return "Image generation is turned off in settings."
    queue_limit = max(1, int(config.get("image_generator_queue_limit", 4) or 4))
    backend = str(config.get("image_generator_backend", "auto") or "auto").lower()
    if backend in {"auto", "gpu"}:
        gpu_queue = max(1, int(config.get("image_generator_gpu_queue_limit", 1) or 1))
        queue_limit = min(queue_limit, gpu_queue)
    with _job_lock:
        if len(_active_jobs) >= queue_limit:
            return "I am still finishing the previous image. Try again in a moment."
    if not bool(config.get("perf_guard_enabled", True)):
        return None
    from silva.media.perf_guard import sample_perf

    snap = sample_perf()
    min_ram = float(config.get("image_generator_min_ram_gb", 1.5) or 1.5)
    max_cpu = float(config.get("image_generator_cpu_max", 80.0) or 80.0)
    log_info(
        f"Image Studio preflight: system {snap.system_cpu:.0f}% "
        f"process {snap.process_cpu:.0f}% ram {snap.avail_ram_gb:.1f}GB"
    )
    if snap.avail_ram_gb < min_ram or snap.process_cpu >= max_cpu:
        return (
            "I am holding off on image generation so the system does not freeze. "
            "Close heavy programs or try again when the PC is freer."
        )
    return None


def _describe(
    prompt: str,
    palette_name: str,
    motifs: list[str],
    history: list[str],
    *,
    aspect: str = "square",
    seed: int | None = None,
    backend: str = "lightweight",
    settings: dict | None = None,
) -> str:
    shape_text = ", ".join(motif.replace("_", " ") for motif in motifs)
    changes = "; ".join(history[1:]) if len(history) > 1 else "none yet"
    if backend == "gpu":
        options = settings or {}
        return (
            f"This is a CUDA-generated neural image built from the request: {prompt.strip() or 'untitled'}. "
            f"It was rendered with {options.get('model', 'a local diffusion model')} in "
            f"{options.get('steps', 'a few')} steps on the GPU. "
            f"The frame is {aspect} with seed {seed if seed is not None else 'random'}, and the visual focus follows "
            f"{shape_text if shape_text else 'the prompt'}. Added changes: {changes}."
        )
    return (
        f"This is a lightweight Silva concept image built from the request: {prompt.strip() or 'untitled'}. "
        f"It uses a {palette_name} palette with layered {shape_text} shapes on a soft gradient background. "
        f"The frame is {aspect}, the motif placement uses seed {seed if seed is not None else 'random'}, "
        "and the composition centers the main motif with smaller geometric accents and a caption strip. "
        f"Added changes: {changes}. "
        "It is a procedural illustration, not a photorealistic model render."
    )


def generate_image(
    prompt: str,
    *,
    user_id: str = "",
    style: str = "auto",
    aspect: str = "square",
    seed: int | None = None,
    test: bool = False,
) -> dict | None:
    text = sanitize_image_prompt(str(prompt or "").strip())
    if not text:
        return None
    refusal = generation_preflight()
    if refusal:
        log_info(f"Image Studio refused generation: {refusal}")
        return {"refusal": refusal}
    token = uuid.uuid4().hex
    with _job_lock:
        _active_jobs.add(token)
    try:
        aspect_name = str(aspect or "square").lower()
        image, meta, settings = _render(
            text, style=style, aspect=aspect_name, seed=seed, test=test
        )
        if image is None:
            return {"refusal": str(meta.get("error") or "The GPU image could not be rendered.")}
        ensure_store()
        image_id = uuid.uuid4().hex[:12]
        path = STORE_DIR / f"{image_id}.png"
        image.save(path)
        palette_name = _palette_name(text)
        motifs = _motifs(text)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        backend = str(meta.get("backend") or "lightweight")
        record = {
            "id": image_id,
            "prompt": text,
            "history": [text],
            "palette": palette_name,
            "motifs": motifs,
            "style": str(style or "auto"),
            "aspect": aspect_name,
            "seed": seed,
            "backend": backend,
            "device": str(meta.get("device") or ""),
            "generation_settings": settings,
            "description": _describe(
                text,
                palette_name,
                motifs,
                [text],
                aspect=aspect_name,
                seed=seed,
                backend=backend,
                settings=settings,
            ),
            "path": str(path),
            "added_by": str(user_id or ""),
            "created_at": now,
            "updated_at": now,
            "size": path.stat().st_size,
        }
        records = load_index()
        records.append(record)
        save_index(records)
        set_active_image(image_id, user_id)
        log_info(
            f"Image Studio generated {image_id} for {user_id or 'default'} "
            f"on {backend}: {text[:100]}"
        )
        return record
    finally:
        with _job_lock:
            _active_jobs.discard(token)


def generate_gpu_test_image(*, user_id: str = "") -> dict | None:
    return generate_image(
        "a small friendly robot on a clean blue background",
        user_id=user_id,
        aspect="square",
        seed=42,
        test=True,
    )


def edit_image(
    image_id: str,
    addition: str,
    *,
    user_id: str = "",
    style: str | None = None,
    aspect: str | None = None,
    seed: int | None = None,
) -> dict | None:
    record = get_generated_image(image_id)
    text = sanitize_image_prompt(str(addition or "").strip())
    if record is None or not text:
        return None
    refusal = generation_preflight()
    if refusal:
        log_info(f"Image Studio refused edit: {refusal}")
        return {"refusal": refusal}
    token = uuid.uuid4().hex
    with _job_lock:
        _active_jobs.add(token)
    try:
        old_path = Path(str(record.get("path") or ""))
        style_name = str(style if style is not None else record.get("style") or "auto")
        aspect_name = str(aspect if aspect is not None else record.get("aspect") or "square").lower()
        seed_value = seed if seed is not None else record.get("seed")
        image, meta, settings = _render(
            f"{record.get('prompt', '')} {text}",
            previous=old_path,
            style=style_name,
            aspect=aspect_name,
            seed=seed_value,
        )
        if image is None:
            return {"refusal": str(meta.get("error") or "The GPU image edit could not be rendered.")}
        new_path = Path(str(old_path))
        image.save(new_path)
        history = [str(item) for item in (record.get("history") or [])]
        history.append(text)
        prompt = f"{record.get('prompt', '')} + {text}"
        palette_name = _palette_name(prompt)
        motifs = _motifs(prompt)
        backend = str(meta.get("backend") or str(record.get("backend") or "lightweight"))
        record.update(
            {
                "prompt": prompt,
                "history": history,
                "palette": palette_name,
                "motifs": motifs,
                "style": style_name,
                "aspect": aspect_name,
                "seed": seed_value,
                "backend": backend,
                "device": str(meta.get("device") or record.get("device") or ""),
                "generation_settings": settings or record.get("generation_settings"),
                "description": _describe(
                    prompt,
                    palette_name,
                    motifs,
                    history,
                    aspect=aspect_name,
                    seed=seed_value,
                    backend=backend,
                    settings=settings or record.get("generation_settings")
                    if isinstance(record.get("generation_settings"), dict)
                    else settings,
                ),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "size": new_path.stat().st_size,
                "added_by": str(user_id or record.get("added_by") or ""),
            }
        )
        save_index([item for item in load_index() if item.get("id") != image_id] + [record])
        set_active_image(str(record["id"]), user_id)
        log_info(f"Image Studio edited {record['id']}: {text[:100]}")
        return record
    finally:
        with _job_lock:
            _active_jobs.discard(token)


def describe_generated_image(image_id: str) -> str:
    record = get_generated_image(image_id)
    if record is None:
        return "I do not have that generated image anymore."
    return apply_safety(str(record.get("description") or _describe(
        str(record.get("prompt") or ""),
        str(record.get("palette") or "paper"),
        list(record.get("motifs") or ["shapes"]),
        list(record.get("history") or []),
        aspect=str(record.get("aspect") or "square"),
        seed=record.get("seed"),
        backend=str(record.get("backend") or "lightweight"),
        settings=record.get("generation_settings") if isinstance(record.get("generation_settings"), dict) else None,
    )))


def save_generated_to_library(image_id: str, *, user_id: str = "") -> dict | None:
    from silva.media.reference_images import add_reference

    record = get_generated_image(image_id)
    if record is None:
        return None
    return add_reference(
        str(record.get("path") or ""),
        category="object",
        label=str(record.get("prompt") or "Generated image")[:80],
        notes=str(record.get("description") or ""),
        source="image_generator",
        added_by=str(user_id or record.get("added_by") or ""),
    )
