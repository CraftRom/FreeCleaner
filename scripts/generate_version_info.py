from __future__ import annotations

import argparse
from pathlib import Path


def normalize_base_version(raw: str) -> tuple[int, int, int, int]:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Base version cannot be empty.")

    if value.lower().startswith("v"):
        value = value[1:]

    if "-" in value:
        value = value.split("-", 1)[0]

    parts = value.split(".")
    if len(parts) == 3:
        parts.append("0")

    if len(parts) != 4:
        raise ValueError(
            f"Version '{raw}' must contain 3 or 4 numeric parts, for example 0.2.0 or 0.2.0.0"
        )

    try:
        ints = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"Version '{raw}' contains a non-numeric part.") from exc

    return ints  # type: ignore[return-value]


def build_version_text(
    *,
    base_version: tuple[int, int, int, int],
    build_number: int,
    product_name: str,
    company_name: str,
    internal_name: str,
    original_filename: str,
    file_description: str,
) -> str:
    base_version_str = ".".join(str(part) for part in base_version)
    full_version_str = f"{base_version_str}-build-{build_number}"

    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={base_version},
    prodvers={base_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
        StringStruct('CompanyName', '{company_name}'),
        StringStruct('FileDescription', '{file_description}'),
        StringStruct('FileVersion', '{full_version_str}'),
        StringStruct('InternalName', '{internal_name}'),
        StringStruct('OriginalFilename', '{original_filename}'),
        StringStruct('ProductName', '{product_name}'),
        StringStruct('ProductVersion', '{full_version_str}')
        ])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PyInstaller version_info.txt for FreeCleaner.")
    parser.add_argument("--base-version", required=True, help="Base numeric version, e.g. 0.2.0.0")
    parser.add_argument("--build-number", required=True, type=int, help="CI build number")
    parser.add_argument("--product-name", default="FreeCleaner")
    parser.add_argument("--company-name", default="FreeCleaner")
    parser.add_argument("--internal-name", default="FreeCleaner")
    parser.add_argument("--original-filename", default="FreeCleaner.exe")
    parser.add_argument(
        "--file-description",
        default="FreeCleaner Windows cleaner, auto system language, and persistent language preference",
    )
    parser.add_argument("--output", default="version_info.txt")
    args = parser.parse_args()

    base_version = normalize_base_version(args.base_version)
    text = build_version_text(
        base_version=base_version,
        build_number=args.build_number,
        product_name=args.product_name,
        company_name=args.company_name,
        internal_name=args.internal_name,
        original_filename=args.original_filename,
        file_description=args.file_description,
    )

    output_path = Path(args.output)
    output_path.write_text(text, encoding="utf-8", newline="\n")
    print(f"Generated {output_path} with version {'.'.join(map(str, base_version))}-build-{args.build_number}")


if __name__ == "__main__":
    main()
