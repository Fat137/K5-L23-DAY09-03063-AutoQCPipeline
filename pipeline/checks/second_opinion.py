"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401


CHECK = "second_opinion"


def _valid_labels(ds, stem):
    """[(số dòng gốc, lớp, box)] của các dòng hợp lệ. Dòng hỏng để label_format báo, ở đây chỉ bỏ qua."""
    labels = []
    for line, text in ds.read_label_lines(stem) or []:
        try:
            cls, *box = parse_yolo_line(text)
        except (ValueError, OverflowError):     # OverflowError: id lớp là "inf"; valid_boxes không bắt ca này
            continue
        if 0 <= cls < len(ds.classes):
            labels.append((line, cls, tuple(box)))
    return labels


def _judge_prediction(cls, box, labels, so):
    """Quyết định cho MỘT dự đoán: trả (mã lỗi, IoU tốt nhất) hoặc None nếu không cờ."""
    cands = [(iou_xywh(box, b), c) for _, c, b in labels]
    cands = [(iou, c) for iou, c in cands if iou >= so["iou_missing"]]
    if not cands:
        return "POSSIBLE_MISSING", 0.0

    same = [iou for iou, c in cands if c == cls]
    if same:
        best = max(same)
        return ("POSSIBLE_LOOSE_BOX", best) if best < so["iou_loose"] else None

    best = max(iou for iou, _ in cands)
    return ("POSSIBLE_WRONG_CLASS", best) if best >= so["iou_match"] else None


def _check_image(ds, stem, rows, cfg):
    so = cfg["second_opinion"]
    size = ds.image_size(stem)
    labels = _valid_labels(ds, stem)
    if size is None:                            # ảnh hỏng: check images báo, ở đây không tính được diện tích px
        return []
    width, height = size
    issues = []

    for row in rows:
        cls, conf, box = row[0], row[1], tuple(row[2:6])
        if conf < so["conf"] or box[2] * width * box[3] * height < so["min_area_px"]:
            continue
        verdict = _judge_prediction(cls, box, labels, so)
        if verdict:
            code, iou = verdict
            message = f"model thấy lớp {ds.classes[cls]} (conf {conf:.2f}), IoU tốt nhất với nhãn {iou:.2f}"
            issues.append(Issue(CHECK, WARN, code, stem, message, extra={"conf": conf, "iou": round(iou, 4)}))

    trusted = [tuple(r[2:6]) for r in rows if r[1] >= so["fp_conf"]]
    for line, cls, box in labels:
        best = max((iou_xywh(box, p) for p in trusted), default=0.0)
        if best < so["iou_missing"]:
            message = f"box lớp {ds.classes[cls]} không khớp vật nào model thấy (IoU tốt nhất {best:.2f})"
            issues.append(Issue(CHECK, WARN, "POSSIBLE_FALSE_POS", stem, message, line, {"iou": round(best, 4)}))
    return issues


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")
    issues = []
    for path in ds.image_files():
        stem = path.stem
        if stem in preds and ds.label_path(stem).exists():
            issues.extend(_check_image(ds, stem, preds[stem], cfg))
    return issues
