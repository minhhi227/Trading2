#!/usr/bin/env python3
"""Convert every HEIC/HEIF image in a Google Drive folder to JPEG, in place.

Reads each HEIC from Drive, decodes it, writes a full-resolution JPEG back into
the same folder. Originals are left untouched.

Usage:
    export GOOGLE_DRIVE_TOKEN="ya29...."
    python3 tools/heic_to_jpg_drive.py <folder_id> [--quality 92] [--dry-run]

The token needs the https://www.googleapis.com/auth/drive scope.
Progress is recorded in <state_dir>/converted.json so re-runs skip finished
files -- useful when an access token expires part way through.
"""

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
HEIF_MIMES = {"image/heif", "image/heic", "image/heif-sequence", "image/heic-sequence"}


class TokenExpired(Exception):
    pass


def request(url, token, method="GET", body=None, headers=None, retries=4):
    """Issue an API call, retrying on transient failures."""
    hdrs = {"Authorization": f"Bearer {token}"}
    hdrs.update(headers or {})
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code == 401:
                raise TokenExpired(detail) from e
            # 403 is used for rate limiting as well as permission errors.
            transient = e.code in (429, 500, 502, 503, 504) or (
                e.code == 403 and "ateLimit" in detail
            )
            if not transient or attempt == retries:
                raise RuntimeError(f"HTTP {e.code} for {url}: {detail}") from e
        except urllib.error.URLError as e:
            if attempt == retries:
                raise RuntimeError(f"network error for {url}: {e}") from e
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def list_heic_files(folder_id, token):
    """Return every HEIC/HEIF file directly inside the folder."""
    files, page_token = [], None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id, name, mimeType, size)",
            "pageSize": "1000",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = json.loads(request(f"{API}/files?{urllib.parse.urlencode(params)}", token))
        for f in payload.get("files", []):
            if f["mimeType"] in HEIF_MIMES or f["name"].lower().endswith((".heic", ".heif")):
                files.append(f)
        page_token = payload.get("nextPageToken")
        if not page_token:
            return files


def existing_names(folder_id, token):
    """Names already present in the folder, so we never collide."""
    names, page_token = set(), None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(name)",
            "pageSize": "1000",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = json.loads(request(f"{API}/files?{urllib.parse.urlencode(params)}", token))
        names.update(f["name"] for f in payload.get("files", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return names


def convert(raw, quality):
    """HEIC bytes -> JPEG bytes, upright, with EXIF carried across."""
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im)  # bake in rotation, normalise the tag
    if im.mode != "RGB":
        im = im.convert("RGB")
    out = io.BytesIO()
    exif = im.info.get("exif")
    im.save(out, "JPEG", quality=quality, subsampling=0, optimize=True,
            **({"exif": exif} if exif else {}))
    return out.getvalue(), im.size


def upload(name, folder_id, data, token):
    """Multipart upload of a single JPEG into the folder."""
    boundary = "===heic2jpg-boundary==="
    metadata = json.dumps({"name": name, "parents": [folder_id]}).encode()
    body = b"".join([
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
        metadata,
        f"\r\n--{boundary}\r\nContent-Type: image/jpeg\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    url = f"{UPLOAD_API}/files?uploadType=multipart&supportsAllDrives=true&fields=id,name,size"
    return json.loads(request(
        url, token, method="POST", body=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    ))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder_id")
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--dry-run", action="store_true", help="list what would be converted")
    ap.add_argument("--state-dir", default=".", help="where converted.json lives")
    args = ap.parse_args()

    token = os.environ.get("GOOGLE_DRIVE_TOKEN", "").strip()
    if not token:
        sys.exit("GOOGLE_DRIVE_TOKEN is not set")

    state_path = os.path.join(args.state_dir, "converted.json")
    done = {}
    if os.path.exists(state_path):
        with open(state_path) as fh:
            done = json.load(fh)

    files = list_heic_files(args.folder_id, token)
    print(f"{len(files)} HEIC/HEIF file(s) in folder; {len(done)} already converted")

    if args.dry_run:
        for f in files:
            mark = "skip" if f["id"] in done else "convert"
            print(f"  [{mark}] {f['name']} ({int(f.get('size', 0)):,} bytes)")
        return

    taken = existing_names(args.folder_id, token)
    failures = []

    for i, f in enumerate(files, 1):
        if f["id"] in done:
            continue

        # Two Drive files can share a name; keep both by suffixing.
        stem = f["name"].rsplit(".", 1)[0]
        name = f"{stem}.jpg"
        n = 2
        while name in taken:
            name = f"{stem} ({n}).jpg"
            n += 1

        try:
            raw = request(f"{API}/files/{f['id']}?alt=media&supportsAllDrives=true", token)
            jpeg, size = convert(raw, args.quality)
            created = upload(name, args.folder_id, jpeg, token)
        except TokenExpired:
            with open(state_path, "w") as fh:
                json.dump(done, fh, indent=2)
            sys.exit(f"\nAccess token expired after {len(done)} file(s). "
                     f"Refresh it and re-run -- progress is saved in {state_path}.")
        except Exception as e:  # keep going; report at the end
            print(f"[{i}/{len(files)}] FAILED {f['name']}: {e}")
            failures.append((f["name"], str(e)))
            continue

        taken.add(name)
        done[f["id"]] = {"source": f["name"], "jpg": name, "jpg_id": created["id"]}
        with open(state_path, "w") as fh:
            json.dump(done, fh, indent=2)
        print(f"[{i}/{len(files)}] {f['name']} -> {name} "
              f"({size[0]}x{size[1]}, {len(jpeg):,} bytes)")

    print(f"\nDone. {len(done)} converted, {len(failures)} failed.")
    for name, err in failures:
        print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
