"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


DROP_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
REMOVE_CODES = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
DROPPED = "(đã xoá dòng)"


def _record(image, line, action, before, after):
    return {"image": image, "line": line, "action": action, "before": before, "after": after}


def _write_lf(path, text):
    """Luôn ghi xuống dòng LF để kết quả giống nhau trên Windows và Linux."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _remove_images(ds, errors):
    """Xoá ảnh + nhãn của các ảnh bị loại; trả (danh sách fix, tập ảnh đã xử lý)."""
    fixes, removed = [], set()
    for issue in errors:
        stem = issue.image
        if stem in removed or not (issue.code in REMOVE_CODES or issue.code.startswith("DUP_IMAGE_")):
            continue
        removed.add(stem)
        files = [p for p in ds.image_files() if p.stem == stem]
        label = ds.label_path(stem)
        if label.exists():
            files.append(label)
        if files:
            before = ", ".join(p.name for p in files)
            for p in files:
                p.unlink()
            fixes.append(_record(stem, None, "remove_image", before, f"đã xoá ({issue.code})"))
    return fixes, removed


def _rename_classes(ds, cfg):
    """Ghi lại `names` trong data.yaml đúng danh sách lớp, giữ các khoá khác."""
    data = {}
    if ds.yaml_path.exists():
        loaded = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {}
    old = data.get("names")
    want = dict(enumerate(cfg["classes"]))
    if old == want or old == list(cfg["classes"]):
        return []
    data["names"] = want
    _write_lf(ds.yaml_path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return [_record("data.yaml", None, "rename_classes", str(old), str(cfg["classes"]))]


def _clip_line(text):
    """Cắt box về trong [0,1]. Trả dòng mới, hoặc None nếu box không còn diện tích / dòng không đọc được."""
    try:
        cls, cx, cy, w, h = parse_yolo_line(text)
    except (ValueError, OverflowError):
        return None
    x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
    x2, y2 = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
    new_w, new_h = round(x2 - x1, 6), round(y2 - y1, 6)     # làm tròn trước khi xét: tránh ghi ra box rộng 0.000000
    if new_w <= 0 or new_h <= 0:
        return None
    return f"{cls} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {new_w:.6f} {new_h:.6f}"


def _fix_label_file(ds, stem, codes_by_line):
    """Sửa một file nhãn theo số dòng GỐC và ghi lại đúng một lần."""
    path = ds.label_path(stem)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    fixes, kept = [], []
    for number, text in enumerate(lines, 1):
        codes = codes_by_line.get(number)
        if not codes or not text.strip():
            kept.append(text)
            continue
        clipped = None if codes & DROP_CODES else _clip_line(text)      # dòng vừa phải xoá vừa phải cắt: xoá thắng
        if clipped is None:
            fixes.append(_record(stem, number, "drop_line", text, DROPPED))
        else:
            fixes.append(_record(stem, number, "clip_box", text, clipped))
            kept.append(clipped)
    if fixes:
        _write_lf(path, "".join(line + "\n" for line in kept))
    return fixes


def fix(ds, issues, cfg):
    errors = [i for i in issues if i.severity == ERROR]         # cảnh báo là việc của người, không động tới
    fixes, removed = _remove_images(ds, errors)

    if any(i.code == "BAD_CLASS_NAME" for i in errors):
        fixes.extend(_rename_classes(ds, cfg))

    needs_label = {i.image for i in errors if i.code == "MISSING_LABEL_FILE"} - removed
    for stem in sorted(needs_label):
        if not ds.label_path(stem).exists():                    # không tạo file rỗng: rỗng nghĩa là "ảnh nền"
            fixes.append(_record(stem, None, "needs_label", "(không có file)", "chuyển người gán"))

    by_file = defaultdict(lambda: defaultdict(set))             # {ảnh: {số dòng gốc: {mã lỗi}}}
    for issue in errors:
        if issue.line is not None and issue.image not in removed and issue.code in DROP_CODES | {"BOX_OUT_OF_IMAGE"}:
            by_file[issue.image][issue.line].add(issue.code)
    for stem in sorted(by_file):
        fixes.extend(_fix_label_file(ds, stem, by_file[stem]))
    return fixes
