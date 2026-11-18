# Báo cáo Day 09 — Phạm Tiến Phát, 03063

## 1. Kết luận trước
Pipeline kết luận **Hold** (mã thoát 10). Lô vào có **224 ảnh**, bước nhận loại 22 ảnh, **202 ảnh** ra bộ `clean_v1`. Đây là **bản nháp, chưa phát hành**.

Lý do: không còn lỗi bắt buộc (0 lỗi), nhưng **38/202 ảnh (18,8%)** còn cảnh báo chưa được người duyệt, vượt ngưỡng Hold 10%. Ngân sách 80 ảnh không phủ hết hàng đợi 125 ảnh.

## 2. Lỗi và phân việc
Số liệu từ `02_error_list_v1` (mẫu số: 224 ảnh ở bước nhận, 202 ảnh ở bước QC).

| Mã lỗi | Số dòng / ảnh | Ai sửa | Vì sao |
|---|---:|---|---|
| `DUP_IMAGE_EXACT` | 8 / 8 | máy (loại ảnh) | md5 trùng từng byte, không cần phán đoán |
| `LEAK_TEST` | 5 / 5 | máy (loại ảnh) | ảnh trùng kho test/val làm metric đẹp giả |
| `DUP_IMAGE_NEAR` | 4 / 4 | máy (loại ảnh) | phash trong ngưỡng đã calibrate |
| `BAD_SIZE` | 3 / 3 | máy (loại ảnh) | cạnh ngắn dưới 250 px |
| `CORRUPT_IMAGE` | 2 / 2 | máy (loại ảnh) | ảnh không đọc được |
| `BOX_OUT_OF_IMAGE` | 8 / 8 | máy (cắt box) | phép cắt về [0,1] xác định, giữ nguyên lớp |
| `DUP_BOX` | 7 / 7 | máy (xoá dòng) | giữ dòng đầu, xoá dòng lặp |
| `BAD_CLASS_ID` | 6 / 6 | máy (xoá dòng) | không suy ra được lớp đúng |
| `BOX_ZERO` | 4 / 4 | máy (xoá dòng) | box không có diện tích |
| `BAD_FORMAT` | 3 / 3 | máy (xoá dòng) | dòng không đọc được |
| `BAD_CLASS_NAME` | 2 / `data.yaml` | máy (đổi tên) | danh sách lớp đã cố định trong cấu hình |
| `MISSING_LABEL_FILE` | 6 / 6 | **người** | máy không được bịa nhãn |
| `POSSIBLE_MISSING` | 53 / 52 | **người** | model chỉ nghi ngờ, có thể sai |
| `POSSIBLE_FALSE_POS` | 29 / 27 | **người** | như trên |
| `POSSIBLE_LOOSE_BOX` | 28 / 24 | **người** | như trên |
| `POSSIBLE_WRONG_CLASS` | 18 / 18 | **người** | nhầm lớp hợp lệ là lỗi ngữ nghĩa |
| `EMPTY_LABEL` | 12 / 12 | **người** | cần xác nhận đúng là ảnh nền |
| `BOX_TINY` / `BOX_HUGE` | 6 / 4 và 3 / 3 | **người** | có thể đúng, cần nhìn ảnh |
| `CLASS_RARE` | 4 / cấp dataset | máy (gián tiếp) | không còn ở `04_error_list_v2` sau khi sửa tự động |

`03_fixes.csv` ghi 35 thay đổi: 20 `drop_line`, 8 `clip_box`, 6 `needs_label`, 1 `rename_classes`.

**Hàng đợi:** điểm ưu tiên là tổng trọng số theo mã lỗi, nhân thêm theo độ tin của model. 6 ảnh `NEEDS_LABEL` (trọng số 10) nằm trong nhóm đầu vì thiếu nhãn sẽ gây Rework. Tiếp theo là ảnh có nhiều nghi ngờ nhầm lớp và thiếu box.

**Ngân sách 80/125 ảnh** phủ được: 6/6 ảnh thiếu nhãn, 18/18 ảnh nghi nhầm lớp, 50/52 ảnh nghi thiếu box, 12/23 ảnh nghi box thừa, 8/24 ảnh nghi box lỏng. Box lỏng có trọng số thấp nhất nên bị bỏ lại nhiều nhất.

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | **10** | `DUP_IMAGE_NEAR`: 1,00 / 0,50 → 1,00 / 0,67 | Cờ này **xoá ảnh** nên ưu tiên precision. 10 là ngưỡng nhỏ nhất bắt đủ 3 cặp trùng thật ở khoảng cách 6–10 trên raw, chưa gộp nhầm ảnh khác nhau. |
| `second_opinion.conf` | 0,25 | **0,6** | `MISSING`: 0,50 / 1,00 → 0,57 / 1,00; `WRONG_CLASS`: 0,56 / 0,83 → 0,62 / 0,83; `LOOSE_BOX`: 0,29 / 0,40 → 0,20 / 0,20; `FALSE_POS`: 0,31 / 1,00 (không đổi) | Ngưỡng cao nhất còn giữ nguyên recall của `MISSING` và `WRONG_CLASS`. Hàng đợi raw giảm từ 143 xuống 125 ảnh. Cái giá là recall `LOOSE_BOX` giảm một nửa. |

**Chỗ calibration có thể đánh lừa:** trên calib, `phash_dist=16` cho recall `DUP_IMAGE_NEAR` cao nhất (0,83) và precision vẫn 1,00. Trên raw, ngưỡng này loại **26 ảnh thay vì 17**. Trong 9 ảnh bị loại thêm, 8 cặp có độ tương quan ảnh rất thấp (`crop_ncc` từ 0,09 đến 0,59; đây là tương quan ảnh xám có thử cả vùng cắt, đo bằng script phân tích riêng), tức gần như chắc chắn là ảnh khác nhau. Ở `phash_dist=20`, số ảnh bị loại lên tới 134/224. Calib chỉ có 39 ảnh nên không lộ ra các va chạm hash này. Kiểm tra bằng mắt 12 cặp có phash từ 3 đến 16 cho thấy **4 cặp trùng thật**: cả 3 cặp ở khoảng cách 6–10 và chỉ 1/9 cặp ở khoảng cách 16. Tăng ngưỡng lên 16 sẽ bắt thêm 1 cặp đúng nhưng xoá nhầm 8 ảnh tốt, nên giữ `phash_dist=10`.

**Không chọn `conf=0,8` dù đó là ngưỡng duy nhất cho Release** (7,9% ảnh còn cảnh báo): recall `MISSING` trên calib giảm từ 1,00 xuống 0,75, nghĩa là hàng đợi nhỏ đi vì checker bỏ sót lỗi, không phải vì dữ liệu sạch hơn.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Gate chặn đúng.** Lệnh `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb` (không có người duyệt) cho kết luận **Rework**, mã thoát **20**, còn 6 lỗi bắt buộc (`MISSING_LABEL_FILE`), và thư mục `work/exp_nb/clean_v1` **không được tạo**.

**(b) Điểm mù có bằng chứng:**
1. **Ảnh trùng bị biến đổi mạnh:** cặp `img_0084` và `img_0074` có phash 16 (ngoài ngưỡng 10), `crop_ncc` = 0,984, và **đã xác nhận bằng mắt là ảnh trùng**, nhưng cả hai vẫn nằm trong `clean_v1`. Cặp này chỉ làm tập train dư 1 ảnh, không rò rỉ sang tập test vì cả hai đều thuộc lô raw. Trên calib, ngưỡng 10 cũng bỏ sót 2/6 ảnh gần trùng.
2. **Box lỏng:** recall `POSSIBLE_LOOSE_BOX` trên calib chỉ 0,20 (bắt 1/5 lỗi chèn), và `07_error_list_v3` còn 20 cảnh báo loại này.
3. **Nhầm lớp mà model lớn cũng nhầm:** recall `POSSIBLE_WRONG_CLASS` là 0,83 (bỏ sót 1/6 lỗi chèn). Các lỗi này không xuất hiện trong báo cáo nào.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Cấu hình: `yolo26n.pt`, 20 epoch, 2 seed (0 và 1), batch 16, ảnh 640 px, GPU trên Colab. Hai biến thể dùng chung tập val (`gold_val`, 40 ảnh) và tập test (100 ảnh). Bảng dưới lấy từ `submission/results/comparison.md`.

| biến thể | #ảnh train | số seed | map50 (TB ± độ lệch) | map50_95 (TB ± độ lệch) | precision (TB ± độ lệch) | recall (TB ± độ lệch) |
|---|---|---|---|---|---|---|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 202 | 2 | 0.701 ± 0.025 | 0.487 ± 0.008 | 0.759 ± 0.003 | 0.625 ± 0.019 |

**Kết luận: không có bằng chứng `clean` tốt hơn `raw`.** Chênh mAP50 (clean − raw) là **−0,025**, xấp xỉ độ lệch chuẩn giữa các seed của `clean` (0,025), nên nằm trong nhiễu. Chênh mAP50-95 là −0,024, lớn hơn độ lệch chuẩn (tối đa 0,008) và cùng chiều ở cả 2 seed, nên `clean` có dấu hiệu thấp hơn. Tuy vậy 2 seed là quá ít để khẳng định.

**Mức giảm tập trung ở lớp truck:** AP50 của truck giảm 0,111 (0,648 → 0,538), trong khi car, person và bus gần như không đổi (+0,001, +0,001, +0,008). AP50 truck của `clean` cũng dao động mạnh giữa 2 seed (0,590 và 0,486).

**Giả thuyết và cách kiểm:**
1. **Nhãn truck trong `clean` không đồng nhất.** Số box truck không giảm mà tăng (32 ở `raw`, 41 ở `clean`), và toàn bộ phần tăng đến từ 80 ảnh người duyệt (16 → 28 box), còn 122 ảnh chưa duyệt vẫn giữ nhãn máy. Lớp này chỉ có 21 ảnh nên dễ bị ảnh hưởng. Cách kiểm: train thêm biến thể `oracle` (toàn bộ nhãn người) với ít nhất 5 seed.
2. **Điểm của `raw` bị thổi phồng do rò rỉ.** `raw` còn 5 ảnh trùng tập test (`LEAK_TEST`), trong đó `img_0101` có box truck. Cách kiểm: đánh giá lại cả hai model trên 95 ảnh test còn lại sau khi bỏ 5 ảnh trùng.
3. **`raw` có nhiều ảnh train hơn** (224 so với 202), dù một phần là ảnh trùng hoặc ảnh hỏng. Cách kiểm: train `raw` trên đúng 202 ảnh của `clean`, chỉ khác nhãn.

**Việc tiếp theo:** duyệt thêm ít nhất 18 ảnh để qua cửa Hold, ưu tiên ảnh có truck, rồi train lại với ít nhất 5 seed.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối: Hold.** Không phát hành `clean_v1`. Để chuyển thành Release cần tỉ lệ ảnh còn cảnh báo dưới 10%, tức tối đa 20/202 ảnh. Nghĩa là người phải duyệt thêm **ít nhất 18 ảnh có cảnh báo** trong số 38 ảnh còn lại (tổng ngân sách tối thiểu 98 ảnh), rồi chạy lại pipeline.

**(b) Có dùng AI (Claude Code) để viết 4 module.**
- **Prompt chính:** yêu cầu AI đọc đề, docstring và test của từng module rồi viết code, với giới hạn: ngưỡng đọc từ `cfg`, không sửa `data/raw`, không đọc đáp án.
- **Cách kiểm:** chạy 79 unit test của đề; thử thêm 16 ca biên (dòng dính 2 lỗi, dòng trống giữa file, id lớp `inf`, nhiều dự đoán trên một ảnh); đối chiếu với lỗi chèn sẵn ở bộ calib; chạy toàn bộ pipeline trên raw.
- **Một lần AI sai:** script phân tích ngưỡng trùng ảnh của AI ban đầu đưa cả 208 cặp vào ảnh ghép để xem lại, gồm rất nhiều cặp không liên quan. Lỗi lộ ra khi đọc kết quả chạy, và script được sửa để chỉ giữ 12 cặp có phash từ 3 đến 16.
