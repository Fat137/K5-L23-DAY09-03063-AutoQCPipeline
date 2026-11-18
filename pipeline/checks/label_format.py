"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401


CHECK = "label_format"


def _check_file(ds, stem, cfg):
    """Kiểm mọi dòng của một file nhãn; dòng hỏng chỉ bị báo, không làm dừng các dòng sau."""
    lf = cfg["label_format"]
    n_classes = len(ds.classes)
    size = ds.image_size(stem)              # None nếu ảnh hỏng/không có ảnh: khi đó bỏ qua BOX_TINY
    issues = []
    seen = []                               # (lớp, box) các dòng hợp lệ phía trước, để tìm box lặp

    def report(severity, code, line, message, extra=None):
        issues.append(Issue(CHECK, severity, code, stem, message, line, extra or {}))

    for line, text in ds.read_label_lines(stem) or []:
        try:
            cls, cx, cy, w, h = parse_yolo_line(text)
        except (ValueError, OverflowError) as e:    # OverflowError: id lớp là "inf" thì int() không đổi được
            report(ERROR, "BAD_FORMAT", line, f"dòng không đúng 5 cột số: {e}")
            continue
        if not 0 <= cls < n_classes:
            report(ERROR, "BAD_CLASS_ID", line, f"id lớp {cls} ngoài 0..{n_classes - 1}")
            continue
        if w <= 0 or h <= 0:
            report(ERROR, "BOX_ZERO", line, f"box không có diện tích: w={w}, h={h}")
            continue

        overflow = max(-(cx - w / 2), -(cy - h / 2), cx + w / 2 - 1, cy + h / 2 - 1)
        if overflow > lf["overflow_tol"]:
            report(ERROR, "BOX_OUT_OF_IMAGE", line, f"box tràn ảnh {overflow:.4f}", {"overflow": round(overflow, 6)})

        box = (cx, cy, w, h)
        if any(c == cls and iou_xywh(box, b) > lf["dup_box_iou"] for c, b in seen):
            report(ERROR, "DUP_BOX", line, f"box lặp với một dòng trước đó cùng lớp {cls}")
        seen.append((cls, box))

        if size and min(w * size[0], h * size[1]) < lf["min_box_px"]:
            report(WARN, "BOX_TINY", line, f"cạnh ngắn của box dưới {lf['min_box_px']} px")
        if w * h > lf["max_box_frac"]:
            report(WARN, "BOX_HUGE", line, f"box phủ {w * h:.0%} diện tích ảnh")
    return issues


def run(ds, cfg):
    issues = []
    for path in ds.label_files():
        issues.extend(_check_file(ds, path.stem, cfg))
    return issues
