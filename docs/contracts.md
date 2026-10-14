# قراردادها

این قرارداد مرز ماژول‌ها و معیار تست‌هاست. نام فیلدها در پیاده‌سازی همین‌هاست. پیام قابل‌نمایش برای کاربر فارسی است. شناسه کدها لاتین و پایدارند.

## ۱. خطا

```text
code            شناسه پایدار، مانند file.unsupported_type
message         فارسی، بدون مسیر دیسک و بدون مقدار سلول
detail          شیء کوچک و امن برای رابط؛ می‌تواند تهی باشد
```

نگاشت HTTP:

| وضعیت | کاربرد |
| --- | --- |
| 400 | ورودی نامعتبر |
| 403 | دسترسی غیرمجاز |
| 404 | فضای کار یا فایل ناشناس |
| 409 | عملیات تغییردهنده دیگری در همین فضای کار در حال اجراست |
| 413 | حجم بیش از سقف |
| 422 | برنامه اجرایی غیرقابل‌قبول |
| 500 | خطای پیش‌بینی‌نشده با پیام عمومی فارسی |

کدهای اولیه:

| کد | معنی |
| --- | --- |
| `file.unsupported_type` | قالب شناخته نشد یا مجاز نیست |
| `file.empty` | فایل صفر بایت |
| `file.too_large` | بیش از سقف طراحی |
| `file.corrupt` | فایل باز نشد |
| `file.unsafe_archive` | بایگانی xlsx از سقف حجم غیرفشرده گذشت |
| `workspace.not_found` | فضای کار موجود نیست |
| `workspace.forbidden` | این شناسه برای این درخواست مجاز نیست |
| `job.conflict` | عملیات دیگری در حال تغییر همین فضاست |
| `job.cancelled` | کاربر لغو کرد |
| `job.interrupted` | فرآیند وسط کار قطع شد |
| `plan.ambiguous` | برای اجرا به پاسخ کاربر نیاز است |
| `plan.confirmation_required` | عملیات حساس منتظر تأیید است |
| `plan.unknown_tool` | ابزاری خارج از فهرست مجاز |
| `output.invalid` | کنترل صحت خروجی رد شد |

## ۲. سلول، ستون، جدول

```text
Cell
  raw          رشته یا تهی؛ همان متن خوانده‌شده
  parsed       عدد Decimal، تاریخ، یا تهی؛ فقط وقتی تجزیه بی‌ابهام باشد
  kind         text | identifier | number | currency | date | boolean | blank | mixed | unknown
  warnings     فهرست کد هشدار

Column
  name                 عنوان اصلی
  normalized_name      برای مقایسه داخلی
  index
  kind                 نوع غالب
  kind_confidence      صفر تا یک
  role_hints           مانند national_id، phone، invoice_no، amount، date، person_name، city
  empty_count
  samples              حداکثر ۵ مقدار خام

Table
  name                 نام برگه یا نام فایل csv
  header_row_index
  header_status        detected | hypothesized
  columns
  rows
```

قاعده نوع:

- اگر نقش ستون شناسه باشد، `kind` برابر `identifier` است؛ حتی وقتی همه مقدارها رقم باشند.
- `parsed` برای شناسه همیشه تهی است. تنها منبع بازتولید، `raw` است.
- ستون با بیش از یک نوع غیرخالی، `mixed` است و به‌اجبار به عدد تبدیل نمی‌شود.

## ۳. گزارش ساختار

```text
Finding
  code
  severity     error | warning | info | hypothesis
  sheet
  address      مانند نام برگه و سلول، اگر مورد مشخص باشد
  count
  message      فارسی
  evidence     شمارش و نمونه شناسه ردیف، نه رونوشت گسترده سلول‌ها

SheetSummary
  name
  row_count              شامل عنوان
  column_count
  data_row_count
  columns
  formula_count
  error_display_count    تعداد نمایش خطای شناخته‌شده
  merged_cell_count
  unsupported            فهرست برچسب ساختارهای پرخطر

StructureReport
  file_id
  version_id
  format                 xlsx | xls | csv
  sheet_count
  sheets
  findings
  unchecked              کارهایی که موتور نتوانست انجام دهد، با دلیل
```

شدت `hypothesis` برای چیزهایی است که محتمل‌اند ولی اثبات نشده‌اند؛ مانند «این ستون احتمالاً مبلغ است» یا «این ردیف پرت به نظر می‌رسد». شدت `error` فقط برای خرابی مشخص است؛ مانند نمایش `#REF!` یا تاریخ نامعتبر.

خطاهای نمایشی که در بررسی جست‌وجو می‌شوند: `#REF!`، `#VALUE!`، `#N/A`، `#DIV/0!`، `#NAME?`، `#NULL!`، `#NUM!`.

اگر فرمول در سلول باشد و مقدار ذخیره‌شده نداشته باشد، یک مورد `unchecked` ثبت می‌شود: نتیجه فرمول ارزیابی نشده است. این مورد تست موفق حساب نمی‌شود.

## ۴. تغییر پاک‌سازی

```text
Change
  sheet
  row_index
  column_index
  before          مقدار خام
  after           مقدار جدید
  rule_id         شناسه قاعده

CleaningReport
  source_version_id
  result_version_id
  changes
  skipped         سلول‌هایی که عمداً دست نخورده‌اند، با دلیل
  stats           تعداد ردیف و ستون قبل و بعد
```

هیچ قاعده‌ای حق ندارد طول شناسه را کم کند یا صفر ابتدایی را بردارد.

قاعده‌های متن که در بخش سه باید وجود داشته باشند:

- `text.trim` فاصله دو سر
- `text.collapse_spaces` فاصله‌های پیاپی داخلی، بدون حذف نیم‌فاصله
- `text.arabic_yeh` تبدیل `ي` و `ى` به `ی`
- `text.arabic_kaf` تبدیل `ك` به `ک`
- `number.parse` فقط تجزیه بی‌ابهام
- `date.parse_jalali` و `date.parse_gregorian`
- `date.ambiguous` بدون تغییر مقدار، فقط هشدار
- `identifier.leading_zeros` شناسه را متن نگه می‌دارد
- `identifier.national_id_checksum` فقط هشدار است؛ رقم کنترلی نامعتبر مقدار را عوض نمی‌کند و ردیف را حذف نمی‌کند

## ۵. مغایرت

```text
MatchStatus
  full_match          کلید و ستون‌های مقایسه‌شده یکی‌اند
  value_mismatch      کلید یکی است و دست‌کم یک ستون مقایسه فرق دارد
  only_left
  only_right
  ambiguous           تطبیق احتمالی؛ تصمیم قطعی نیست

ReconcileRow
  status
  key
  confidence          صفر تا یک؛ برای تطبیق دقیق ۱
  left_values
  right_values
  amount_left         Decimal یا تهی
  amount_right
  amount_delta        قدرمطلق تفاوت
  amount_delta_ratio  تهی اگر مبنا صفر باشد یا مبلغ نامعتبر باشد
  reason              علت اختلاف، فارسی
  evidence            شواهد کوتاه؛ مانند نام ستون‌های متفاوت یا امتیاز شباهت

ReconcileReport
  left_version_id
  right_version_id
  key_columns
  key_decision        detected | confirmed_by_user
  rows
  summary
  validation          نتیجه هویت شمارش
```

هویت شمارش، که تست باید آن را بشکند اگر نقض شود:

```text
تعداد ردیف داده چپ
  = full_match + value_mismatch + only_left + ردیف‌های چپِ داخل ambiguous

تعداد ردیف داده راست
  = full_match + value_mismatch + only_right + ردیف‌های راستِ داخل ambiguous
```

هر ردیف ورودی دقیقاً در یک دسته قرار دارد. ردیف مبهم همزمان در «فقط فایل اول» یا «منطبق» نیست.

اگر ستون مبلغ مشخص باشد:

```text
جمع مبلغ چپ = جمع مبلغ ردیف‌های چپ در هر پنج نقش
```

محاسبه با `Decimal` است. اختلاف یک واحد در آخرین رقم مقیاس پول (ریال بدون اعشار، یا دو رقم اگر اعشار واقعی در داده باشد) پذیرفته است. بیشتر از آن، `output.invalid` است.

برگه‌های فایل خروجی مغایرت:

- خلاصه
- منطبق
- مغایر
- فقط فایل اول
- فقط فایل دوم
- مشکوک
- درباره این خروجی

## ۶. برنامه اجرایی

```text
Step
  tool
  params          شیء؛ رشته کد نیست
  reads
  writes

Ambiguity
  code
  question        یک سؤال کوتاه فارسی
  choices         گزینه‌های قابل انتخاب؛ می‌تواند تهی باشد

OperationPlan
  id
  workspace_id
  user_text
  goal
  steps
  ambiguities
  requires_confirmation
  confirmation_reasons
  risks
  source          rules | llm | quick_action
```

ابزار خارج از رجیستری باعث `plan.unknown_tool` می‌شود. پارامتر حاوی مسیر مطلق، `..`، یا کلیدهای اجرایی (`code`، `script`، `shell`) رد می‌شود.

رجیستری نهایی ابزارها:

| ابزار | بخش ورود به رجیستری |
| --- | --- |
| `inspect` | ۲ |
| `preview` | ۲ |
| `clean` | ۳ |
| `reconcile` | ۴ |
| `filter` | ۵ |
| `sort` | ۵ |
| `add_column` | ۵ |
| `compute_column` | ۵ |
| `aggregate` | ۷ |
| `rank` | ۷ |
| `trend` | ۷ |
| `outliers` | ۷ |
| `kpi` | ۷ |
| `report` | ۷ |
| `chart` | ۸ |
| `dashboard` | ۸ |
| `apply_formula` | ۸ |
| `create_workbook` | ۹ |
| `sheet_add` `sheet_delete` `sheet_rename` `sheet_move` | ۹ |
| `sheet_merge` `sheet_split` `file_merge` `file_split` | ۹ |
| `column_add` `column_delete` `column_move` | ۹ |
| `row_add` `row_delete` | ۹ |
| `format_cells` `freeze` `data_validation` | ۹ |
| `export` | ۶ برای دانلود نسخه موجود؛ ۹ برای قالب‌های متنوع ساخت‌یافته |
| `restore_version` | ۱۰ |

تا قبل از بخش مربوط، ابزار در رجیستری نیست. برنامه‌ریز آن را پیشنهاد نمی‌دهد و رابط دکمه‌اش را نشان نمی‌دهد.

## ۷. وضعیت عملیات

```text
pending
running
waiting_confirmation
succeeded
failed
cancelled
```

فیلدهای قابل‌نمایش:

```text
id
status
progress_current
progress_total
progress_label     فارسی
summary            پس از پایان
warnings
error              فقط در شکست
outputs            شناسه نسخه و نام پیشنهادی دانلود
```

`summary` در حالتی غیر از `succeeded` ادعای تکمیل نمی‌کند.

## ۸. نسخه

```text
Version
  id
  file_id
  parent_version_id
  kind               original | derived
  blob_name          فقط شناسه؛ نه نام کاربر
  operation_id
  sha256
  byte_size
  row_count          تهی تا وقتی بررسی انجام شود
  sheet_count
  created_at
  note
```

بازگشت موفق یعنی `current_version_id` برابر نسخه انتخاب‌شده شود و دانلود بعدی همان بایت‌ها را بدهد. تست باید برابری checksum را بررسی کند.

## ۹. تحلیل و توضیح

```text
AnalysisResult
  metrics[]          name، value به‌صورت رشته Decimal، unit
  groups[]
  caveats[]          فارسی؛ مانند کم بودن نمونه
```

متن مدیریتی یا از همین `metrics` با قالب جمله ساخته می‌شود، یا پس از تولید آزاد، هر عدد موجود در متن با این فهرست مطابقت داده می‌شود. عدد ناسازگار متن را نامعتبر می‌کند.

شاخص‌های الزامی که در صورت وجود ستون مناسب باید قابل محاسبه‌باشند: مجموع، میانگین، میانه، کمینه، بیشینه، رتبه، رشد یا کاهش بین دو دوره، روند زمانی، توزیع دسته، مقایسه دسته‌ها، مقدار پرت. اگر ستون لازم وجود نداشته باشد، نتیجه آن شاخص «قابل محاسبه نیست» با ذکر ستون غایب است، نه عدد ساختگی.

مقدار پرت یک `hypothesis` است. تنها بودنِ فاصله از جمع، اثبات غلط بودن مقدار نیست.

## ۱۰. نمودار و داشبورد

```text
ChartSpec
  chart_type     column | bar | line | pie | scatter | area | combo
  title
  category_field
  series[]       name، value_field
  source         شناسه جدول واقعی

DashboardSpec
  title
  cards[]        ارجاع به metric
  charts[]       ChartSpec
```

داده نمودار همان جدول منبع است. سری ثابت نمایشی ممنوع است.

داشبورد فروش، اگر ستون‌های فروش و مشتری و محصول و شهر و تاریخ در داده باشند، این کارت‌ها را می‌سازد: مجموع فروش، تعداد مشتری، میانگین فروش، پرفروش‌ترین محصول، پرفروش‌ترین شهر، روند ماهانه، فروش دسته‌بندی. کارت بدون ستون پشتیبان حذف می‌شود و در محدودیت‌ها نام برده می‌شود.

## ۱۱. زمینه گفتگو

```text
ConversationFocus
  file_ids
  sheet_name
  columns
  last_plan_id
  last_result_version_id
  last_period_label
```

زمینه فقط داخل همان فضای کار معتبر است. اشاره مبهم اجرا تولید نمی‌کند.

## ۱۲. پیش‌نمایش عملیات حساس

قبل از اجرای مشمول تأیید، رابط این‌ها را نشان می‌دهد:

- شرح کار
- فایل و برگه هدف
- ستون یا ردیف درگیر
- تعداد رکورد درگیر
- ریسک و ابهام
- این‌که فایل اصلی دست نمی‌خورد و نسخه جدید ساخته می‌شود، یا در صورت استثنا دلیل تفاوت

مثال پیام شمارش: «۲۳۴ ردیف برای این اصلاح شناسایی شده‌اند.» عدد باید با نتیجه ابزار پیش‌نمایش یکی باشد.

## ۱۳. دسترسی API فضای کار (حداقل پایدار)

| روش | مسیر | از بخش |
| --- | --- | --- |
| POST | `/api/workspaces` | ۱ |
| GET | `/api/workspaces/{id}` | ۱ |
| POST | `/api/workspaces/{id}/files` | ۱ |
| GET | `/api/workspaces/{id}/files` | ۱ |
| GET | `/api/workspaces/{id}/files/{file_id}` | ۱ |
| GET | `/api/workspaces/{id}/versions/{version_id}/download` | ۱ |
| POST | `/api/workspaces/{id}/inspections` | ۲ |
| POST | `/api/workspaces/{id}/operations` | ۵ به بعد، با رشد ابزارها |
| POST | `/api/workspaces/{id}/operations/{op_id}/confirm` | ۵ |
| POST | `/api/workspaces/{id}/operations/{op_id}/cancel` | ۶ |
| GET | `/api/workspaces/{id}/operations/{op_id}` | ۵ |
| POST | `/api/workspaces/{id}/versions/{version_id}/restore` | ۱۰ |

بدنه و پاسخ این مسیرها فیلدهای همین سند را برمی‌گردانند، نه شکل موازی دیگری.
