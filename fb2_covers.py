#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FB2 Cover Extractor + A4 Contact Sheet

Что делает:
1. Ищет все .fb2 в папке input_fb2
2. Извлекает обложку из каждого файла
3. Сохраняет обложки в папку extracted_covers
4. Создаёт PDF A4 с обложками нужного физического размера

Зависимости:
    pip install pillow reportlab
"""

from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# =========================
# НАСТРОЙКИ
# =========================

INPUT_DIR = Path("../")
OUTPUT_DIR = Path("extracted_covers")
PDF_NAME = "covers_A4.pdf"

# Размер одной обложки на бумаге:
COVER_WIDTH_CM = 5.0
COVER_HEIGHT_CM = 6.5

# Поля листа:
MARGIN_CM = 1.0

# Расстояние между картинками:
GAP_CM = 0.5

# True = сохранять пропорции и добавлять белые поля,
# False = обрезать края, чтобы точно заполнить 4×6 см
KEEP_FULL_COVER = True

# Разрешение промежуточных изображений для печати
PRINT_DPI = 300


def cm(value: float) -> float:
    """Сантиметры -> точки PDF."""
    return value * 72.0 / 2.54


def safe_filename(name: str) -> str:
    """Убирает символы, запрещённые в именах файлов Windows."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "cover"


def local_name(tag: str) -> str:
    """Возвращает имя XML-тега без namespace."""
    return tag.split("}", 1)[-1]


def get_book_title(root: ET.Element, fallback: str) -> str:
    """Пытается получить название книги из description/title-info/book-title."""
    for elem in root.iter():
        if local_name(elem.tag) == "book-title":
            text = "".join(elem.itertext()).strip()
            if text:
                return text
    return fallback


def find_cover_reference(root: ET.Element) -> Optional[str]:
    """Находит href картинки, указанной в <coverpage><image .../>."""
    for elem in root.iter():
        if local_name(elem.tag) != "coverpage":
            continue

        for child in elem.iter():
            if local_name(child.tag) != "image":
                continue

            for attr_name, value in child.attrib.items():
                if local_name(attr_name) == "href" and value:
                    return value.lstrip("#")

    return None


def find_binary(root: ET.Element, binary_id: str) -> Optional[Tuple[bytes, str]]:
    """Ищет <binary id="..."> и декодирует Base64."""
    for elem in root.iter():
        if local_name(elem.tag) != "binary":
            continue

        if elem.attrib.get("id") != binary_id:
            continue

        raw = "".join(elem.itertext())
        raw = re.sub(r"\s+", "", raw)

        if not raw:
            return None

        try:
            data = base64.b64decode(raw)
        except Exception:
            return None

        content_type = elem.attrib.get("content-type", "").lower()
        return data, content_type

    return None


def extension_for(content_type: str, image: Image.Image) -> str:
    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    if "gif" in content_type:
        return ".gif"

    fmt = (image.format or "").lower()
    if fmt in ("jpeg", "jpg"):
        return ".jpg"
    if fmt:
        return "." + fmt

    return ".png"


def extract_cover(fb2_path: Path, output_dir: Path) -> Optional[Path]:
    """Извлекает обложку из одного FB2."""
    try:
        tree = ET.parse(fb2_path)
        root = tree.getroot()
    except Exception as exc:
        print(f"[ОШИБКА XML] {fb2_path.name}: {exc}")
        return None

    cover_id = find_cover_reference(root)
    if not cover_id:
        print(f"[НЕТ ОБЛОЖКИ] {fb2_path.name}")
        return None

    binary = find_binary(root, cover_id)
    if not binary:
        print(f"[НЕ НАЙДЕНА КАРТИНКА] {fb2_path.name}: {cover_id}")
        return None

    data, content_type = binary

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        print(f"[БИТАЯ ОБЛОЖКА] {fb2_path.name}: {exc}")
        return None

    title = get_book_title(root, fb2_path.stem)
    ext = extension_for(content_type, image)

    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{safe_filename(title)}{ext}"

    counter = 2
    while out_path.exists():
        out_path = output_dir / f"{safe_filename(title)} ({counter}){ext}"
        counter += 1

    if ext == ".jpg":
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(out_path, "JPEG", quality=95)
    elif ext == ".png":
        image.save(out_path, "PNG")
    elif ext == ".webp":
        image.save(out_path, "WEBP", quality=95)
    else:
        out_path = out_path.with_suffix(".png")
        image.save(out_path, "PNG")

    print(f"[OK] {fb2_path.name} -> {out_path.name}")
    return out_path


def make_print_image(image_path: Path, width_px: int, height_px: int) -> Image.Image:
    """Готовит картинку строго нужного размера, сохраняя пропорции."""
    img = Image.open(image_path).convert("RGB")

    if KEEP_FULL_COVER:
        # ВАЖНО: масштабируем и вниз, и вверх.
        # thumbnail() не подходит, потому что он никогда не увеличивает маленькие изображения.
        scale = min(width_px / img.width, height_px / img.height)

        new_width = max(1, round(img.width * scale))
        new_height = max(1, round(img.height * scale))

        img = img.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )

        background = Image.new("RGB", (width_px, height_px), "white")
        x = (width_px - new_width) // 2
        y = (height_px - new_height) // 2
        background.paste(img, (x, y))
        return background

    return ImageOps.fit(
        img,
        (width_px, height_px),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def create_pdf(image_paths: list[Path], pdf_path: Path) -> None:
    """Собирает изображения в PDF A4."""
    if not image_paths:
        print("Нет обложек для PDF.")
        return

    page_w, page_h = A4

    cover_w = cm(COVER_WIDTH_CM)
    cover_h = cm(COVER_HEIGHT_CM)
    margin = cm(MARGIN_CM)
    gap = cm(GAP_CM)

    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin

    cols = max(1, int((usable_w + gap) // (cover_w + gap)))
    rows = max(1, int((usable_h + gap) // (cover_h + gap)))
    per_page = cols * rows

    print(
        f"\nPDF: {cols} × {rows} = {per_page} обложек на лист A4 "
        f"({COVER_WIDTH_CM:g}×{COVER_HEIGHT_CM:g} см)"
    )

    c = canvas.Canvas(str(pdf_path), pagesize=A4)

    width_px = round(COVER_WIDTH_CM / 2.54 * PRINT_DPI)
    height_px = round(COVER_HEIGHT_CM / 2.54 * PRINT_DPI)

    tmp_dir = OUTPUT_DIR / "_print_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        for index, image_path in enumerate(image_paths):
            pos = index % per_page

            if index > 0 and pos == 0:
                c.showPage()

            row = pos // cols
            col = pos % cols

            x = margin + col * (cover_w + gap)
            y = page_h - margin - cover_h - row * (cover_h + gap)

            prepared = make_print_image(image_path, width_px, height_px)
            tmp_path = tmp_dir / f"{index:04d}.jpg"
            prepared.save(tmp_path, "JPEG", quality=95, dpi=(PRINT_DPI, PRINT_DPI))

            c.drawImage(
                str(tmp_path),
                x,
                y,
                width=cover_w,
                height=cover_h,
                preserveAspectRatio=False,
                mask="auto",
            )

        c.save()
    finally:
        for p in tmp_dir.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except Exception:
            pass

    print(f"[ГОТОВО] PDF: {pdf_path.resolve()}")


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fb2_files = sorted(INPUT_DIR.glob("*.fb2"))

    if not fb2_files:
        print(
            f"В папке {INPUT_DIR.resolve()} пока нет .fb2 файлов.\n"
            "Положи книги туда и запусти скрипт ещё раз."
        )
        input("\nНажми Enter, чтобы закрыть...")
        return

    extracted: list[Path] = []

    print(f"Найдено FB2: {len(fb2_files)}\n")

    for fb2 in fb2_files:
        cover = extract_cover(fb2, OUTPUT_DIR)
        if cover:
            extracted.append(cover)

    if extracted:
        create_pdf(extracted, Path(PDF_NAME))

    print(
        f"\nГотово.\n"
        f"Извлечено обложек: {len(extracted)} из {len(fb2_files)}."
    )

    input("\nНажми Enter, чтобы закрыть...")


if __name__ == "__main__":
    main()
