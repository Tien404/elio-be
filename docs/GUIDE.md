# Hướng dẫn backend ELIO

<a id="architecture"></a>
## Kiến trúc

```text
HTTP → app/api/routes → app/services → app/infrastructure/db/repositories
     → pyodbc → Microsoft ODBC Driver → SQL Server
```

Route parse DTO/trả HTTP; service giữ quyền, state, thời gian và transaction; repository chứa T-SQL/row mapping. Domain ở app/domain; interfaces ở app/ports/interfaces.py. API và worker dùng chung services; pages thuộc React.

| Service | Trách nhiệm |
|---|---|
| AuthService | Account, session, password, operational admin |
| CourseService | Catalog, offering, enrollment, teaching team |
| ContentService | Topic, material, announcement |
| SubmissionService | Assignment, group, submission/version/receipt |
| GradingService | Grade revisions, publication, gradebook |
| QuizService | Question bank, publication copies, attempts, finalize/release |
| NotificationService | Personal inbox và recipient events |

Files MATERIAL qua ContentService; SUBMISSION/ASSIGNMENT_ATTACHMENT qua SubmissionService, cùng private FileStorage và file-asset policy. Admin operational access không cấp quyền đọc học liệu/bài/điểm riêng tư.

Mapping từng API→route→service→FR/screen nằm trong [API Explorer](api-explorer.html). Đối chiếu class/component/data diagrams tại nguồn thiết kế của dự án.

<a id="rules"></a>
## Quy tắc nghiệp vụ

| Mảng | Hợp đồng |
|---|---|
| API | /api/v1; integer IDs dương; /courses là catalog, /offerings là lớp. Page/pageSize mặc định25/tối đa100, thứ tự ổn định; timestamps UTC, UI giờ Việt Nam/tiếng Anh. |
| Identity | Admin cấp account, email login; /me chỉ sửa displayName. Phiên mật khẩu tạm chỉ đổi mật khẩu/logout. Change/reset password thu hồi tất cả session, kể cả hiện tại. Hash có salt; khóa account bởi admin. |
| Access | Opaque session cookie HttpOnly/Secure/SameSite=Lax; mutation có CSRF. Backend kiểm current account/role/membership/resource/owner, gồm upload/download/replay/CSV. |
| Offering | UNIQUE(course,semester,section). Draft/Open có một active lead, nhiều co-instructor. Transfer toàn bộ lead responsibilities Draft/Open trước khóa account; transfer xác nhận mật khẩu người thao tác. Admin staffing exception cần reason/audit. Archived có thể giữ locked lead nhưng cần active lead trước restore. |
| Archive | Học thuật chỉ đọc; restore giữ deadline/history. Chặn archive khi còn unexpired attempt; expired attempts phải finalize thành công. |
| Assignment | Material TEXT/LINK/FILE; assignment/quiz có topic tùy chọn cùng offering. open≤due≤cutoff; confirm mới được nhận tới đúng cutoff, grade chỉ khi DB time>cutoff. Sau publish chỉ kéo dài due/cutoff trước bất kỳ saved grade/missing-zero nào. |
| Files | Upload private bytes+file_assets trước confirm. Unattached staging hết hạn24h; attached files không bị cleanup. Material≤50MB; assignment attachments tối đa5×20MB; submission1–5×20MB (decimal bytes). Mọi loại tệp, download attachment/nosniff. |
| Confirm/retry | Một transaction lưu version/files/key/hash/receipt. Cùng actor/key/payload trả receipt gốc sau current-access check, kể cả sau cutoff; payload khác409, lệnh mới stale412. Chỉ confirmSubmission dùng Idempotency-Key. |
| Grades | Chấm khi offering Open và có current teaching access. Grade gắn submission; revisions đầy đủ/bất biến, tách draft/published pointers. Sửa riêng giữ published score/feedback tới republish; sửa sau publish cần reason. Missing-zero là NOT_SUBMITTED container, không version/file/receipt/completion. |
| Groups | Mọi eligible member được nộp; một điểm chung. Freeze từng nhóm ở first confirm/reasoned missing-zero, gồm mọi assigned recipient kể cả locked account. Current access vẫn cần active. |
| Quiz | Bank editable; publish copy prompt/options/key/explanation/points bất biến. Max=sum points; score ở attempt. Một attempt/student/quiz. Schedule/duration khóa từ first attempt; endsAt=min(closeAt,start+duration). Start/save trước end, save tại end bị chặn. |
| Quiz finalize | Attempt version/ETag; saves xếp hàng, seal sau pending saves. Worker lock/finalize durable answers một lần và catch-up sau restart. Lỗi không thành0. Tự release sau close+finalized+offering Open; archived chờ restore, đã release đọc theo current access. |
| Progress/gradebook | Checklist mandatory published hiện tại là mẫu số, completion độc lập điểm; missing-zero không complete, N=0 có thông báo. Gradebook dùng assignment published revisions+quiz released attempts; final thang10 khi đủ kết quả và weights=100%, không normalize thiếu. |
| Events/ops | Notification/audit an toàn, loại actor khỏi audience, không lộ score/feedback/key/private bytes. Durable recipient event cùng transaction, retry không nhân bản. Backup/restore thủ công gồm DB+files nhất quán; RTO mục tiêu4h. |

Phạm vi không gồm representative, reopen graded work, grade withdrawal, manual quiz regrade, generic retry ledger, login throttling bắt buộc, batch enrollment, account/Aiken imports, random grouping, audit CSV, forum/replies, membership suspension, AI/chat/realtime/native app. Gradebook CSV thuộc Sprint2.

<a id="database"></a>
## Database và transaction

[Logical model](../app/contracts/logical-model.json) chứa38 quan hệ; T-SQL scripts đặt trong sql/migrations/, repository trong app/infrastructure/db/repositories/.

| Dữ liệu | SQL Server |
|---|---|
| ID/key | INT; IDENTITY cho ID tự sinh; PK/candidate/composite keys theo model |
| Chuỗi | NVARCHAR(n)/NVARCHAR(MAX); collation đúng cho email/code/private key/hash |
| Score/weight | DECIMAL(p,s) đúng precision/scale |
| Timestamp | DATETIMEOFFSET(7), UTC; không dùng SQL Server TIMESTAMP cho datetime |
| State/version | BIT/CHECK cho trạng thái; INT/BIGINT counter cho version/ETag |
| Integrity | FK/CHECK/XOR/filtered UNIQUE INDEX đúng offering/assignment; kiểm NULL/cascade paths |

Một use case dùng cùng connection, autocommit=False; commit một lần khi thành công, rollback/close khi lỗi. Repository không commit riêng; bind ? parameters, whitelist identifiers/sort, đóng cursor và map rows tường minh. Dùng DB UTC cho cutoff; OUTPUT INSERTED lấy ID, OFFSET/FETCH phân trang. Phân loại SQLSTATE/native codes theo context, giữ diagnostics/credentials khỏi HTTP/log.

Grade với pointers NULL → insert revision → update pointers trong cùng transaction. Kiểm isolation/locks và races trên SQL Server thật; fake DB-API tests chỉ kiểm adapter. Retry writes theo contract khi mất phản hồi.

Schema scripts đánh số theo dependency; ghi prerequisite/target DB/transaction/rollback/post-check. Chạy bằng SSMS/sqlcmd trên DB cách ly và lưu scripts đã áp dụng. GO là batch separator của công cụ, không gửi qua cursor.execute. API startup không migrate database.

<a id="implementation"></a>
## Thứ tự triển khai

| Bước | Đầu ra |
|---|---|
| B0 | Chạy ứng dụng/ODBC connection check; map38 relations/constraints/queries theo dependency; xử lý contract gaps liên quan |
| B1 | Identity schema/repositories/seed cách ly; account/session/password/CSRF/policy thật |
| B2 | Catalog/offering/enrollment; unique section, create+lead atomic, team foundation |
| B3 | Private files/materials; durable bytes+metadata, attach/download/cleanup |
| B4 | Individual assignment/upload/confirm/resubmit/history/receipt; cutoff/replay/concurrent/stale tests |
| B5 | Grade/revisions/publication/correction/missing-zero; own published results |
| B6 | Dashboard và MVP E2E/restart/recovery/manual backup checks |
| Sprint2 | Full team/group/quiz/gradebook CSV/announcements/inbox/calendar/progress/admin |

Mỗi operation: DTO → session/CSRF → service policy+transaction → repository → contract response/error → tests. Khai báo Pydantic request/response model và HTTP status trực tiếp tại route; FastAPI sinh Swagger.

[OpenAPI](../app/contracts/openapi.json) và API Explorer là contract tham chiếu. Viết/sửa route, DTO và service trực tiếp theo từng chức năng; giữ method/path/operationId và thêm tests tương ứng. Khi sửa hợp đồng, cập nhật route/DTO, OpenAPI tham chiếu và API Explorer nhất quán. Các JSON trong app/contracts không được nạp vào runtime.

<a id="contract-gaps"></a>
## Contract cần làm rõ

| ID | Phần còn thiếu | Cần hoàn tất trước |
|---|---|---|
| API-G01 | EnrollmentRequest chỉ có code, thiếu student/account ID cho teacher manual enrollment | B2: request + teacher guard + membership uniqueness |
| API-G02 | UpdateOfferingRequest thiếu regenerate/disable join code | B2: command/fields và teaching permission |
| API-G03 | AssignmentRequest thiếu attachment asset IDs | B4: asset refs/purpose/count/size/same-offering validation |
| API-G04 | Join modal chỉ nhập6-char code, endpoint cần offeringId | B2: luồng xác định offeringId, bảo vệ private offerings |
| API-G05 | Kênh giao mật khẩu tạm cho provision/reset chưa cụ thể | B1: UI/API credential delivery, không log/lưu public password |
| API-G06 | PATCH offering và POST restore cùng hỗ trợ restore | B2: shared service/guard, state/history nhất quán |

Đồng bộ contract/DTO/tests với nhóm trước triển khai chức năng liên quan. listCourses/getCourse dùng /offerings; xác định ID theo path/schema.
