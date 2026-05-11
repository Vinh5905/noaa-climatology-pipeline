## 0. THÔNG TIN DỰ ÁN

| Trường                  | Giá trị                                                         |
| ------------------------- | ----------------------------------------------------------------- |
| Tên dự án              | `noaa-climatology-pipeline`                                     |
| Git remote                | `git@github.com:Vinh5905/noaa-climatology-pipeline.git`         |
| Branch chính             | `main`                                                          |
| Dataset                   | NOAA Global Historical Climatology Network (GHCN-D)               |
| Tham khảo dataset        | https://clickhouse.com/docs/getting-started/example-datasets/noaa |
| Tham khảo phân tích    | https://clickhouse.com/blog/real-world-data-noaa-climate-data     |
| Tham khảo SQL Playground | https://sql.clickhouse.com (cluster `noaa`)                     |
| Quy mô                   | ~2.6 tỷ rows (1 tỷ pre-load, phần còn lại stream ~1M rows/s) |

---

## 1. PHÂN TÍCH BÀI TOÁN & QUYẾT ĐỊNH KIẾN TRÚC

### 1.1. Hiểu dataset

NOAA GHCN-Daily là dataset đo lường khí hậu hàng ngày từ hàng chục nghìn trạm trên toàn thế giới, từ ~1763 đến nay. Schema đã chuẩn hóa (theo ClickHouse blog):

```
station_id   String        -- VD: USC00011084
date         Date          -- ngày đo
tempAvg      Int32         -- nhiệt độ TB (1/10 °C)
tempMax      Int32         -- nhiệt độ max
tempMin      Int32         -- nhiệt độ min
precipitation UInt32       -- lượng mưa (1/10 mm)
snowfall     UInt32        -- tuyết rơi (mm)
snowDepth    UInt32        -- độ dày tuyết (mm)
percentDailySun UInt8      -- % nắng trong ngày
averageWindSpeed UInt32    -- tốc độ gió TB (1/10 m/s)
maxWindSpeed UInt32        -- tốc độ gió max
weatherType  Enum8         -- loại thời tiết
location     Point         -- (lat, lon)
elevation    Float32       -- độ cao (m)
name         LowCardinality(String) -- tên trạm
```

Đặc tính:

- **Time-series, partition theo năm** rất hợp lý
- **Skew theo trạm**: vài nghìn trạm chiếm phần lớn record
- **Sparse**: nhiều cột rỗng cho từng row

### 1.2. Chiến lược 1B pre-load + streaming phần còn lại

1. **Pre-load** (~1B rows): các năm cũ (1763 → ~2010) load trực tiếp vào ClickHouse qua `INSERT FROM s3()`. Đây là **initial backfill** pattern chuẩn của DE.
2. **Streaming** (~1.6B rows): các năm 2011 → 2024 đẩy qua Kafka → ClickHouse Kafka Engine, mô phỏng "data mới chảy vào hệ thống đang sống".
3. **Tốc độ stream**: target **~1M rows/s** ở producer (chấp nhận 200K-800K trên laptop).

### 1.3. Ingestion strategy: chỉ dùng custom producer 

- **Backfill 1B rows**: `INSERT FROM s3()` trực tiếp trong ClickHouse (chuẩn DE pattern)
- **Streaming**: Custom Python producer dùng `confluent-kafka` (librdkafka) → đạt high throughput, full control
- **Metadata stations**: load 1 lần qua `INSERT FROM url()` hoặc producer riêng

1.4. Lựa chọn Orchestration: Dagster (không phải Airflow)

| Tiêu chí        | Airflow                                   | Dagster                                                                       | Thắng         |
| ----------------- | ----------------------------------------- | ----------------------------------------------------------------------------- | -------------- |
| Mô hình         | Task-based DAG                            | Asset-based (data products)                                                   | Dagster cho DW |
| Tích hợp dbt    | Qua `airflow-dbt` hoặc Cosmos          | **Native `dagster-dbt`**, mỗi model = một asset, lineage tự động | Dagster        |
| Local dev         | Cần init DB, webserver, scheduler riêng | `dagster dev` 1 lệnh                                                       | Dagster        |
| Type checking     | Không                                    | Pythonic types + Pydantic                                                     | Dagster        |
| Observability     | Cần plugin                               | Built-in asset materialization, IO managers, partition tracking               | Dagster        |
| Cộng đồng      | Lớn hơn, lâu đời                     | Đang phát triển nhanh                                                      | Airflow        |
| Streaming + batch | Trung bình                               | Tốt (sensors, partitions, declarative scheduling)                            | Dagster        |

**Quyết định: Dagster.** Lý do chính: tích hợp dbt native, mỗi model dbt = một asset có lineage tự động, sensors dễ viết cho Kafka monitoring, local dev đơn giản.

### 1.5. Sơ đồ kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                              │
│  NOAA S3 bucket (CSV gz, by year)    NOAA stations metadata       │
└──────────────┬───────────────────────────┬───────────────────────┘
               │ (1) Bulk backfill         │ (2) One-time metadata
               │ INSERT FROM s3()           │ INSERT FROM url()
               ▼                           ▼
       ┌──────────────────┐         ┌──────────────────┐
       │ ClickHouse RAW   │◀────────│   Apache Kafka   │
       │  (MergeTree)     │  Kafka  │  (KRaft mode)    │
       │  1B pre-loaded   │ Engine  │  topic: noaa.obs │
       └────────┬─────────┘  + MV   └────────▲─────────┘
                │                            │
                │                  (3) Streaming
                │                  Custom Python Producer
                │                  (~1M rows/s, librdkafka)
                ▼
       ┌──────────────────┐
       │       dbt        │  staging → intermediate → marts
       │ (dbt-clickhouse) │
       └────────┬─────────┘
                ▼
       ┌──────────────────┐
       │   ClickHouse     │   stg_*, int_*, mart_*
       │   MARTS layer    │
       └────────┬─────────┘
                │
        ┌───────┼───────┬─────────────────┐
        ▼       ▼       ▼                 ▼
  ┌─────────┐ ┌──────┐ ┌─────────┐  ┌──────────────┐
  │Metabase │ │Grafana│ │ SQL    │  │clickhouse-   │
  │(BI mart)│ │(realt)│ │Playground│ │backup        │
  │monthly  │ │+alert │ │(FastAPI │ │(daily +      │
  │yearly   │ │       │ │ +HTMX)  │ │ on-demand)   │
  └─────────┘ └──────┘ └─────────┘  └──────────────┘

         ▲
         │
   ┌─────┴──────┐
   │  Dagster   │  ◀── orchestrates ALL of the above
   │  (assets + │      schedules, sensors, dbt assets,
   │  dbt-asset)│      backup job, retention job
   └────────────┘
```

---

## 2. STACK CÔNG NGHỆ CHI TIẾT

| Layer                    | Tool                      | Version                | Lý do                                 |
| ------------------------ | ------------------------- | ---------------------- | -------------------------------------- |
| Data Warehouse           | ClickHouse                | 24.x                   | OLAP performance số 1, yêu cầu user |
| Streaming                | Apache Kafka              | 3.7+ (KRaft)           | Không Zookeeper, đơn giản hơn     |
| Transform                | dbt-core + dbt-clickhouse | dbt 1.8+, adapter 1.8+ | Tiêu chuẩn ngành                    |
| Orchestration            | Dagster                   | 1.9+                   | Phân tích 1.4                        |
| Producer                 | Python + confluent-kafka  | 2.x                    | Đạt high throughput                  |
| BI Reporting             | Metabase                  | 0.51+                  | Dễ dùng, có ClickHouse driver       |
| Real-time Monitoring     | Grafana                   | 11.x                   | Plugin ClickHouse official             |
| **SQL Playground** | FastAPI + HTMX + Monaco   | latest                 | Python stack, DE-friendly              |
| **Backup**         | clickhouse-backup         | 2.5+                   | De-facto cho ClickHouse                |
| Container                | Docker Compose            | v2                     | Local-first                            |
| Language                 | Python                    | 3.11                   | Dagster yêu cầu                      |
| Package manager          | uv                        | latest                 | Nhanh hơn pip                         |
| Code quality             | ruff, mypy                | latest                 | Lint + type check                      |
| CI                       | GitHub Actions            | -                      | Free cho public repo                   |

---

## 3. CẤU TRÚC THƯ MỤC

```
noaa-climatology-pipeline/
├── .github/
│   └── workflows/
│       ├── ci.yml                    # Lint + dbt parse + smoke test
│       └── nightly-backup.yml        # (Optional) trigger remote backup
├── .gitignore
├── .env.example
├── README.md
├── PLAN.md                            # File này
├── ARCHITECTURE.md
├── RUNBOOK.md                         # MỚI: hướng dẫn xử lý incident
├── SLA.md                             # MỚI: định nghĩa data freshness SLO
├── Makefile
│
├── docker/
│   ├── docker-compose.yml
│   ├── docker-compose.override.yml.example
│   ├── clickhouse/
│   │   ├── config.d/
│   │   │   ├── logging.xml
│   │   │   └── storage.xml          # Storage policy cho TTL
│   │   ├── users.d/default-user.xml
│   │   └── init-scripts/01-create-databases.sql
│   ├── kafka/server.properties
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── datasources/clickhouse.yml
│   │   │   ├── dashboards/dashboards.yml
│   │   │   └── alerting/
│   │   │       ├── contact-points.yml
│   │   │       └── rules.yml         # MỚI: alert rules
│   │   └── dashboards/
│   │       ├── pipeline-realtime.json
│   │       └── clickhouse-system.json
│   └── metabase/plugins/
│
├── ingestion/
│   ├── pyproject.toml
│   ├── README.md
│   ├── backfill/
│   │   ├── __init__.py
│   │   ├── load_historical.py        # INSERT FROM s3()
│   │   ├── load_stations.py          # MỚI: INSERT FROM url() cho metadata
│   │   └── verify_backfill.py
│   └── producer/
│       ├── __init__.py
│       ├── noaa_producer.py
│       ├── rate_limiter.py
│       └── config.py
│
├── transform/                         # dbt project
│   ├── dbt_project.yml
│   ├── profiles.yml.example
│   ├── packages.yml
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   ├── macros/
│   ├── tests/singular/
│   ├── seeds/country_codes.csv
│   └── snapshots/                     # MỚI: snapshot cho slowly-changing dim
│
├── orchestration/                     # Dagster
│   ├── pyproject.toml
│   ├── README.md
│   ├── noaa_dagster/
│   │   ├── definitions.py
│   │   ├── assets/
│   │   │   ├── backfill.py
│   │   │   ├── kafka_topics.py
│   │   │   ├── dbt_assets.py
│   │   │   ├── monitoring.py
│   │   │   └── lifecycle.py           # MỚI: TTL & partition cleanup
│   │   ├── resources/
│   │   │   ├── clickhouse.py
│   │   │   ├── kafka.py
│   │   │   ├── dbt.py
│   │   │   └── backup.py              # MỚI: clickhouse-backup wrapper
│   │   ├── jobs/
│   │   │   ├── streaming_job.py
│   │   │   ├── transform_job.py
│   │   │   ├── backup_job.py          # MỚI
│   │   │   └── retention_job.py       # MỚI
│   │   ├── schedules/                 # MỚI: tách thư mục riêng
│   │   │   ├── __init__.py
│   │   │   ├── hourly.py
│   │   │   ├── daily.py
│   │   │   └── weekly.py
│   │   ├── sensors/
│   │   │   ├── kafka_lag_sensor.py
│   │   │   └── freshness_sensor.py    # MỚI: SLA freshness
│   │   └── partitions.py
│   └── tests/
│
├── playground/                        # MỚI: SQL Playground web
│   ├── pyproject.toml
│   ├── README.md
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── clickhouse_client.py
│   │   ├── query_loader.py            # Load predefined queries từ YAML
│   │   ├── models.py                  # Pydantic models
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── index.html
│   │   │   └── partials/
│   │   │       ├── result_table.html
│   │   │       ├── query_stats.html
│   │   │       └── query_list.html
│   │   └── static/
│   │       ├── css/main.css
│   │       └── js/editor.js           # Monaco editor init
│   ├── queries/                       # Query definitions (YAML)
│   │   ├── analytics/
│   │   │   ├── avg_precipitation_by_country.yaml
│   │   │   ├── highest_temp_in_portugal.yaml
│   │   │   ├── highest_temp_in_portugal_join.yaml
│   │   │   ├── highest_temp_in_portugal_subquery.yaml
│   │   │   ├── highest_temp_in_portugal_dict_unopt.yaml
│   │   │   ├── highest_temp_in_portugal_dict_opt.yaml
│   │   │   ├── highest_temp_world.yaml
│   │   │   ├── hottest_areas_us_mexico.yaml
│   │   │   ├── find_best_holiday_conditions.yaml
│   │   │   └── group_locations_by_temperature.yaml
│   │   ├── benchmarks/
│   │   │   ├── columns_size_codec_v1.yaml
│   │   │   ├── columns_size_codec_v2.yaml
│   │   │   ├── columns_size_codec_v3.yaml
│   │   │   ├── columns_size_codec_v4.yaml
│   │   │   ├── columns_size_codec_optimal.yaml
│   │   │   ├── table_size_codec_v1.yaml
│   │   │   └── most_effective_codec_per_column.yaml
│   │   └── ops/
│   │       ├── count_all_rows.yaml
│   │       ├── show_tables.yaml
│   │       ├── min_max_boundaries.yaml
│   │       ├── stations_no_precipitation.yaml
│   │       └── select_one_entry_from_dict.yaml
│   └── tests/
│
├── monitoring/
│   ├── grafana/dashboards/            # Source-of-truth JSON
│   └── queries/
│       ├── ingestion_rate.sql
│       ├── kafka_lag.sql
│       └── data_freshness.sql         # MỚI
│
├── reporting/
│   └── metabase/
│       ├── README.md
│       └── dashboards/exported/
│
├── backup/                            # MỚI: backup configs & scripts
│   ├── README.md
│   ├── clickhouse-backup-config.yml
│   ├── scripts/
│   │   ├── backup_full.sh
│   │   ├── backup_incremental.sh
│   │   ├── restore.sh
│   │   └── verify_backup.sh
│   └── retention_policy.md            # RPO/RTO definition
│
├── scripts/
│   ├── bootstrap.sh
│   ├── seed_clickhouse.sh
│   ├── start_producer.sh
│   ├── stop_all.sh
│   ├── health_check.sh
│   └── load_test.sh                   # MỚI: throughput test producer
│
└── tests/
    └── e2e/
        └── test_pipeline_end_to_end.py
```

---

## 4. `.gitignore` (BẮT BUỘC TẠO Ở PHASE 0)

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
.uv/
*.egg-info/
build/
dist/

# Env & secrets
.env
.env.local
.env.*.local
*.pem
*.key
secrets/
profiles.yml
!profiles.yml.example
!**/profiles.yml.example

# dbt
target/
dbt_packages/
logs/
.user.yml

# Dagster
.dagster/
storage/
history/
schedules/
tmp_dagster_home_*/

# Docker & data
docker/clickhouse/data/
docker/clickhouse/logs/
docker/kafka/data/
docker/kafka/logs/
docker/metabase/data/
docker/grafana/data/
docker-compose.override.yml
*.log

# Backup artifacts
backup/storage/
*.tar.gz
*.zst

# Data files
data/
*.csv
*.csv.gz
*.parquet
*.json
!seeds/*.csv
!playground/queries/**/*.yaml
!playground/queries/**/*.yml

# IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store

# OS
Thumbs.db

# Test artifacts
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# Jupyter
.ipynb_checkpoints/
*.ipynb
```

---

## 5. QUY TẮC GIT WORKFLOW (BẮT BUỘC)

### 5.1. Commit conventions (Conventional Commits)

```
<type>(<scope>): <subject>

[optional body]
```

| Type         | Khi dùng                      |
| ------------ | ------------------------------ |
| `feat`     | Thêm chức năng mới         |
| `fix`      | Sửa bug                       |
| `chore`    | Cập nhật config, deps        |
| `docs`     | Sửa docs                      |
| `refactor` | Refactor không đổi behavior |
| `test`     | Thêm/sửa test                |
| `infra`    | Thay đổi Docker, CI          |
| `perf`     | Tối ưu performance           |

Scope ví dụ: `clickhouse`, `dbt`, `dagster`, `kafka`, `producer`, `grafana`, `metabase`, `playground`, `backup`, `lifecycle`, `docker`, `ci`.

### 5.2. Quy tắc auto-commit & push

**SAU MỖI chức năng nhỏ HOẠT ĐỘNG ĐƯỢC** (acceptance criteria pass):

```bash
git add <files đã đổi>
git commit -m "<type>(<scope>): <subject>"
git push origin main
```

**KHÔNG**: gom nhiều feature, push khi chưa pass, commit `.env`/`data/`/secrets.

**SETUP LẦN ĐẦU**:

```bash
git init
git add .
git commit -m "chore(init): bootstrap project skeleton"
git remote add origin git@github.com:Vinh5905/noaa-climatology-pipeline.git
git branch -M main
git push -u origin main
```

Nếu remote đã có content:

```bash
git pull origin main --rebase --allow-unrelated-histories
git push -u origin main
```

### 5.3. Branch strategy

- Làm trực tiếp trên `main` (dự án thực hành cá nhân)
- Thử nghiệm rủi ro: branch `experiment/<name>`, không merge nếu fail

---

## 6. DATA ENGINEERING STANDARDS (CROSS-CUTTING)

> Section này gom các nguyên tắc của ngành DE mà mọi phase phải tuân thủ. Không phải code, mà là **mindset**.

### 6.1. Idempotency (Tính bất biến khi rerun)

**Nguyên tắc**: rerun một job/task lần thứ 2 với cùng input → cùng output, không tạo duplicate.

**Áp dụng trong dự án**:

- Backfill script: dùng `INSERT INTO ... SELECT ... WHERE NOT EXISTS` hoặc cờ `--skip-existing-partitions`
- Producer: ghi message_key = `station_id|date` để consumer có thể dedupe
- dbt models: dùng `materialized='incremental'` với `unique_key`
- Dagster: partition theo năm/tháng để rerun 1 partition không ảnh hưởng partition khác

### 6.2. Backfill capability (Khả năng replay lịch sử)

**Nguyên tắc**: phải có thể replay bất kỳ time window nào trong quá khứ.

**Áp dụng**:

- Backfill script nhận `--start-year` và `--end-year`
- Dagster partitions theo year + có UI để materialize backfill range
- Producer nhận `--years 2015,2016,2017` để replay

### 6.3. Data Quality & Data Contracts

**Nguyên tắc**: schema phải được khai báo rõ, test phải tự động.

**Áp dụng**:

- dbt schema tests trong `_models.yml` (not_null, unique, accepted_values, relationships)
- Singular tests cho business rules (no future dates, temp trong range hợp lý)
- Pydantic models trong producer để validate trước khi gửi Kafka
- (Nice-to-have) JSON Schema cho topic Kafka, lưu trong `data_contracts/`

### 6.4. Backup & Disaster Recovery

**Định nghĩa cần có**:

- **RPO (Recovery Point Objective)**: chấp nhận mất bao nhiêu data → target 24h
- **RTO (Recovery Time Objective)**: bao lâu khôi phục được → target 1h
- **Backup tool**: `clickhouse-backup` (Phase 10)
- **Restore drill**: ít nhất 1 lần manual restore test → document trong RUNBOOK.md

### 6.5. Schema Evolution

**Nguyên tắc**: thêm cột là OK (backward compatible), xóa/đổi tên cột là KHÔNG OK (breaking change).

**Áp dụng**:

- Producer dùng JSON (forward-compat tự nhiên), consumer ignore field thừa
- ClickHouse: `ALTER TABLE ADD COLUMN ... DEFAULT ...` thay vì drop & recreate
- dbt: thêm version vào model name khi breaking change (`mart_temp_v2.sql`)

### 6.6. Observability (3 trụ cột)

| Pillar            | Tool trong dự án                                                        | Mục đích       |
| ----------------- | ------------------------------------------------------------------------- | ----------------- |
| **Logs**    | Container logs (`docker compose logs`), structured logging trong Python | Debug             |
| **Metrics** | Grafana + ClickHouse `system.*` tables                                  | Health monitoring |
| **Traces**  | (Ngoài scope, mention OpenTelemetry là chuẩn)                          | Distributed debug |

Mọi script Python BẮT BUỘC dùng `logging` (không print) với format `[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s`.

### 6.7. Alerting & On-call

**Nguyên tắc**: mọi metric quan trọng phải có alert; mọi alert phải có runbook.

**Áp dụng**:

- Grafana alert rules (Phase 7):
  - Ingestion rate = 0 trong 5 phút
  - Kafka consumer lag > 1M messages
  - ClickHouse disk usage > 80%
  - dbt test failure
- Contact point: webhook (có thể dummy URL hoặc Slack/Discord webhook nếu user có)
- Mỗi alert có link tới section trong `RUNBOOK.md`

### 6.8. SLA / SLO (Service Level Agreement / Objective)

**Định nghĩa trong `SLA.md`**:

- **Data freshness**: 95% data trong `noaa_marts.*` cũ không quá 1h so với `now()`
- **Availability**: pipeline ingestion uptime ≥ 99% (đo theo Dagster run success rate)
- **Completeness**: ≥ 99% rows từ Kafka topic vào được ClickHouse (đo qua _kafka_offset)

Sensor `freshness_sensor` trong Dagster check liên tục.

### 6.9. Secrets Management

**Nguyên tắc**: ZERO password/key trong git.

**Áp dụng**:

- `.env` luôn trong `.gitignore`
- `.env.example` commit với placeholder
- dbt `profiles.yml` đọc từ env: `password: "{{ env_var('CLICKHOUSE_PASSWORD') }}"`
- Pre-commit hook check secret (nice-to-have, dùng `detect-secrets`)

### 6.10. Cost & Resource Awareness

Dù chạy local, vẫn track:

- ClickHouse disk usage per table (Grafana panel)
- Query duration heavy hitters (`system.query_log`)
- Kafka topic retention bytes
- Mục đích: tập thói quen "data có giá", chuẩn bị production

### 6.11. Documentation & Runbooks

**Required docs**:

- `README.md`: quickstart
- `ARCHITECTURE.md`: trade-offs, decisions
- `RUNBOOK.md`: 5+ scenarios common ops (xem 7.7)
- `SLA.md`: SLO definitions
- `backup/retention_policy.md`: backup strategy
- `playground/README.md`: how to add new queries
- dbt docs (`dbt docs serve`)

### 6.12. Reproducibility

- Mọi Python project có `pyproject.toml` + `uv.lock` (commit lockfile)
- Docker images pin version cụ thể (KHÔNG `latest`)
- dbt packages pin version trong `packages.yml`
- ClickHouse DDL có version comment (`-- v1: created 2026-01-01`)

---

## 7. CÁC PHASE THỰC THI

### PHASE 0 — KHỞI TẠO REPO & FOLDER STRUCTURE

**Mục tiêu**: dựng xương sống thư mục, init git, push lên remote.

**Deliverables**:

- [ ] Toàn bộ folder rỗng (`.gitkeep`) đúng mục 3
- [ ] `.gitignore` đúng mục 4
- [ ] `README.md`: tóm tắt, sơ đồ, prerequisites, quick-start
- [ ] `ARCHITECTURE.md`: copy section 1.5 + trade-offs
- [ ] `RUNBOOK.md`: placeholder với danh sách scenarios sẽ fill ở các phase
- [ ] `SLA.md`: định nghĩa SLO theo 6.8
- [ ] `.env.example` đầy đủ
- [ ] `Makefile`: `up`, `down`, `logs`, `clean`, `bootstrap`, `seed`, `producer`, `dbt-run`, `dagster-dev`, `playground`, `backup`, `health`
- [ ] Init git, push lên remote

**`.env.example`**:

```bash
# ClickHouse
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_HTTP_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=changeme
CLICKHOUSE_DB=noaa

# Kafka
KAFKA_BOOTSTRAP=localhost:9092
KAFKA_TOPIC_OBSERVATIONS=noaa.observations
KAFKA_TOPIC_STATIONS=noaa.stations
KAFKA_NUM_PARTITIONS=12
KAFKA_REPLICATION=1

# Producer
PRODUCER_RATE_PER_SEC=1000000
PRODUCER_BATCH_SIZE=10000
PRODUCER_LINGER_MS=5

# Dagster
DAGSTER_HOME=./.dagster

# Grafana
GF_SECURITY_ADMIN_PASSWORD=changeme

# Metabase
MB_DB_FILE=/metabase-data/metabase.db

# Playground
PLAYGROUND_HOST=0.0.0.0
PLAYGROUND_PORT=8080
PLAYGROUND_QUERY_TIMEOUT_SEC=30
PLAYGROUND_MAX_ROWS=10000

# Backup
BACKUP_S3_BUCKET=                # Optional: local-only nếu rỗng
BACKUP_RETENTION_DAYS=30
```

**Acceptance Criteria**:

- `tree -L 2` cho ra đúng structure (kể cả folder mới: `playground/`, `backup/`)
- `git log --oneline` có ≥ 1 commit
- `git remote -v` trỏ đúng
- `git ls-files | grep '\.env$'` trả rỗng

**Commit point**: `chore(init): bootstrap project skeleton and folder structure`

---

### PHASE 1 — DOCKER COMPOSE STACK

**Mục tiêu**: dựng infra local 1 lệnh `docker compose up -d`.

**Deliverables**:

- [ ] `docker/docker-compose.yml` với services: `clickhouse`, `kafka`, `kafka-ui` (Redpanda Console hoặc kafdrop), `grafana`, `metabase`
- [ ] ClickHouse: enable `system.query_log`, `system.metric_log`; cấu hình max_memory hợp lý
- [ ] ClickHouse init: tạo databases `noaa_raw`, `noaa_staging`, `noaa_marts`, `noaa_ops`
- [ ] Kafka KRaft mode, 12 partitions cho `noaa.observations`
- [ ] Grafana provisioning: datasource ClickHouse
- [ ] Metabase: data volume persistent, có ClickHouse driver jar
- [ ] `scripts/health_check.sh` ping 4 services

**Sample skeleton** (agent expand thêm):

```yaml
services:
  clickhouse:
    image: clickhouse/clickhouse-server:24.10
    ports: ["8123:8123", "9000:9000"]
    volumes:
      - ./clickhouse/data:/var/lib/clickhouse
      - ./clickhouse/config.d:/etc/clickhouse-server/config.d:ro
      - ./clickhouse/users.d:/etc/clickhouse-server/users.d:ro
      - ./clickhouse/init-scripts:/docker-entrypoint-initdb.d:ro
    ulimits:
      nofile: { soft: 262144, hard: 262144 }
    environment:
      CLICKHOUSE_DB: ${CLICKHOUSE_DB}
      CLICKHOUSE_USER: ${CLICKHOUSE_USER}
      CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD}

  kafka:
    image: bitnami/kafka:3.7
    ports: ["9092:9092"]
    environment:
      KAFKA_CFG_NODE_ID: 1
      KAFKA_CFG_PROCESS_ROLES: controller,broker
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CFG_NUM_PARTITIONS: 12
    volumes: ["./kafka/data:/bitnami/kafka"]

  grafana:
    image: grafana/grafana-oss:11.3.0
    ports: ["3000:3000"]
    environment:
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
      GF_SECURITY_ADMIN_PASSWORD: ${GF_SECURITY_ADMIN_PASSWORD}
    volumes:
      - ./grafana/data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro

  metabase:
    image: metabase/metabase:v0.51.0
    ports: ["3001:3000"]
    environment:
      MB_DB_FILE: /metabase-data/metabase.db
    volumes:
      - ./metabase/data:/metabase-data
      - ./metabase/plugins:/plugins
```

**Port map** (lưu trong README):

| Port        | Service                     |
| ----------- | --------------------------- |
| 8123 / 9000 | ClickHouse                  |
| 9092        | Kafka                       |
| 3000        | Grafana                     |
| 3001        | Metabase                    |
| 3002        | Dagster (Phase 6)           |
| 8080        | SQL Playground (Phase 9)    |
| 8000        | (free / Kafka UI nếu cần) |

**Acceptance Criteria**:

- `docker compose up -d` → tất cả Healthy < 60s
- `curl http://localhost:8123/ping` trả `Ok.`
- `curl http://localhost:3000/api/health` OK
- `curl http://localhost:3001/api/health` OK
- `scripts/health_check.sh` exit 0

**Commit point**: `infra(docker): add full docker-compose stack with clickhouse kafka grafana metabase`

---

### PHASE 2 — BULK BACKFILL 1B ROWS LỊCH SỬ

**Mục tiêu**: load ~1B rows lịch sử trực tiếp vào ClickHouse từ NOAA S3.

**Deliverables**:

- [ ] `ingestion/backfill/load_historical.py` (clickhouse-connect, `INSERT FROM s3()`)
- [ ] `ingestion/backfill/load_stations.py` (one-time metadata sync qua `INSERT FROM url()`)
- [ ] Bảng `noaa_raw.observations_historical` MergeTree, PARTITION BY toYYYY(date), ORDER BY (station_id, date)
- [ ] Bảng `noaa_raw.stations` cho metadata
- [ ] `ingestion/backfill/verify_backfill.py`: count, validate range, check partition sizes
- [ ] README hướng dẫn chạy
- [ ] **Idempotency check**: script bỏ qua year đã load (kiểm tra qua `system.parts`)

**SQL DDL**:

```sql
CREATE TABLE IF NOT EXISTS noaa_raw.observations_historical (
    station_id      LowCardinality(String),
    date            Date,
    tempAvg         Int32 CODEC(Delta, ZSTD),
    tempMax         Int32 CODEC(Delta, ZSTD),
    tempMin         Int32 CODEC(Delta, ZSTD),
    precipitation   UInt32 CODEC(ZSTD),
    snowfall        UInt32 CODEC(ZSTD),
    snowDepth       UInt32 CODEC(ZSTD),
    percentDailySun UInt8,
    averageWindSpeed UInt32,
    maxWindSpeed    UInt32,
    weatherType     Enum8('Normal'=0,'Fog'=1,'HeavyFog'=2,'Thunder'=3,'SmallHail'=4,'Hail'=5,'Glaze'=6,'Dust'=7,'Smoke'=8,'Blowing'=9,'Tornado'=10,'HighWind'=11,'Mist'=12,'Drizzle'=13,'FreezingDrizzle'=14,'Rain'=15,'FreezingRain'=16,'Snow'=17,'UnknownPrecip'=18,'Ground'=19,'Freezing'=20),
    location        Point,
    elevation       Float32,
    name            LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYYYY(date)
ORDER BY (station_id, date)
SETTINGS index_granularity = 8192;
```

**Chiến lược load**:

- Range 1763 → 2010
- Chia theo năm để dễ resume
- Log mỗi năm: timestamp, rows, duration
- Skip năm đã load (check `system.parts` có partition `YYYY`)

**Acceptance Criteria**:

- `SELECT count() FROM noaa_raw.observations_historical` ≥ 800M
- `SELECT min(date), max(date)` trả range hợp lý
- Rerun script 2 lần → không double-insert
- Log file trong `data/logs/backfill_<timestamp>.log`

**Commit point**: `feat(backfill): implement idempotent historical bulk load from NOAA S3`

---

### PHASE 3 — HIGH-THROUGHPUT KAFKA PRODUCER

**Mục tiêu**: producer Python đẩy NOAA observations vào Kafka với rate target 1M rows/s.

**Deliverables**:

- [ ] `ingestion/producer/noaa_producer.py`:
  - Đọc CSV NOAA (năm 2011-2024) chunk-wise (pyarrow hoặc pandas chunksize)
  - `confluent_kafka.Producer` với config tối ưu:
    ```python
    {
      'bootstrap.servers': KAFKA_BOOTSTRAP,
      'linger.ms': 5,
      'batch.num.messages': 10000,
      'compression.type': 'lz4',
      'queue.buffering.max.kbytes': 1048576,
      'queue.buffering.max.messages': 1000000,
      'acks': '1',
    }
    ```
  - Message key = `station_id|date` (cho idempotent consumer)
  - JSON serialization (comment chỉ ra Avro tốt hơn production)
  - Rate-limiter token bucket trong `rate_limiter.py`
- [ ] CLI: `--rate`, `--years`, `--max-rows`, `--dry-run`, `--start-from-offset`
- [ ] Metrics in stdout mỗi giây: `[rate] target=X actual=Y rows/s, sent=Z, errors=N`
- [ ] Unit test cho `rate_limiter`
- [ ] `scripts/load_test.sh`: chạy producer ở rate khác nhau, log throughput

**Lưu ý**:

- 1M rows/s là target lý thuyết. Trên laptop ~200K-800K. **Không crash, chỉ warn** nếu không đạt.
- Topic `noaa.observations` phải có 12 partitions để Kafka không bottleneck.

**Acceptance Criteria**:

- `python noaa_producer.py --max-rows 100000 --rate 50000` → 100K records trong < 5s
- `kafka-console-consumer --topic noaa.observations --max-messages 10` ra 10 JSON
- Producer in metric mỗi giây
- Unit test rate_limiter pass

**Commit point**: `feat(producer): high-throughput NOAA Kafka producer with token-bucket rate limiter`

---

### PHASE 4 — KAFKA → CLICKHOUSE INGESTION

**Mục tiêu**: ClickHouse consume Kafka topic real-time → MergeTree.

**Deliverables**:

- [ ] DDL 3 bảng pattern Kafka Engine → MV → MergeTree:
  ```sql
  CREATE TABLE noaa_raw.observations_kafka (...)
  ENGINE = Kafka
  SETTINGS kafka_broker_list = 'kafka:9092',
           kafka_topic_list = 'noaa.observations',
           kafka_group_name = 'clickhouse_noaa_consumer',
           kafka_format = 'JSONEachRow',
           kafka_num_consumers = 4,
           kafka_max_block_size = 100000;

  CREATE TABLE noaa_raw.observations_streaming (
      -- cùng schema observations_historical
      _kafka_offset UInt64,
      _kafka_partition UInt32,
      _ingested_at DateTime DEFAULT now()
  )
  ENGINE = MergeTree
  PARTITION BY toYYYY(date)
  ORDER BY (station_id, date);

  CREATE MATERIALIZED VIEW noaa_raw.observations_mv TO noaa_raw.observations_streaming AS
  SELECT *, _offset AS _kafka_offset, _partition AS _kafka_partition, now() AS _ingested_at
  FROM noaa_raw.observations_kafka;
  ```
- [ ] `scripts/setup_kafka_ingestion.sh` chạy DDL
- [ ] View `noaa_raw.observations_all` UNION historical + streaming
- [ ] **Dead Letter Queue**: bảng `noaa_raw.observations_dlq` cho row malformed (qua `kafka_handle_error_mode = 'stream'`)

**Acceptance Criteria**:

- Producer chạy 30s → `count(observations_streaming)` tăng
- `system.kafka_consumers` cho thấy 4 consumers active
- `max(_ingested_at)` cập nhật mỗi vài giây
- Gửi 1 JSON cố tình malformed → vào DLQ, không crash MV

**Commit point**: `feat(clickhouse): add Kafka engine ingestion with MV and DLQ pattern`

---

### PHASE 5 — DBT TRANSFORM LAYER

**Mục tiêu**: chuẩn hóa staging → intermediate → marts.

**Deliverables**:

- [ ] `transform/dbt_project.yml` với profile `noaa_clickhouse`
- [ ] `transform/profiles.yml.example` (KHÔNG commit profiles.yml thật, dùng env var)
- [ ] `transform/packages.yml` với `dbt-labs/dbt_utils`
- [ ] Models:

**Staging (`materialized='view'`)**:

- `stg_noaa__observations.sql`: UNION historical + streaming, normalize, filter date <= today
- `stg_noaa__stations.sql`: parse stations metadata

**Intermediate (`materialized='table'`)**:

- `int_observations_enriched.sql`: JOIN với stations, thêm country, region
- `int_station_yearly_agg.sql`: aggregate theo station + year

**Marts (`materialized='table'` hoặc `incremental` cho mart lớn)**:

- `mart_global_temperature_yearly.sql`
- `mart_extreme_weather_events.sql`
- `mart_top_hottest_stations.sql`
- `mart_precipitation_by_country.sql`
- `mart_ingestion_metrics.sql` (operational, lấy từ `_ingested_at`)

- [ ] Schema tests trong `_models.yml`:
  - `not_null`, `unique`, `accepted_values`, `relationships`
- [ ] Singular tests:
  - `assert_no_future_dates.sql`
  - `assert_temp_in_valid_range.sql` (-90°C đến +60°C)
  - `assert_no_orphan_stations.sql`
- [ ] Snapshot cho stations metadata (slowly-changing dim) trong `snapshots/`
- [ ] dbt docs generate được

**Naming convention**:

- `stg_<source>__<entity>` (2 underscore)
- `int_<description>`
- `mart_<business_area>__<grain>` hoặc `mart_<name>`

**Acceptance Criteria**:

- `dbt deps && dbt parse` không lỗi
- `dbt build` (run + test) pass ≥ 90% tests
- `mart_global_temperature_yearly` có ≥ 200 rows
- `dbt docs generate && dbt docs serve` xem được lineage

**Commit point** (chia nhỏ):

- `feat(dbt): init dbt project with clickhouse profile and packages`
- `feat(dbt): add staging models for observations and stations`
- `feat(dbt): add intermediate models with station enrichment`
- `feat(dbt): add climate marts and operational metrics`
- `test(dbt): add schema and singular tests`

---

### PHASE 6 — DAGSTER ORCHESTRATION + SCHEDULES

**Mục tiêu**: gom toàn bộ pipeline thành Dagster assets với lineage rõ ràng + schedule chuẩn DE.

**Deliverables**:

**A. Definitions**:

- [ ] `orchestration/noaa_dagster/definitions.py` entry point
- [ ] Resources: `ClickHouseResource`, `KafkaProducerResource`, `DbtCliResource`, `BackupResource`

**B. Assets**:

- [ ] `historical_observations`: chạy backfill script
- [ ] `kafka_topics_provisioned`: tạo topic nếu chưa có
- [ ] `streaming_observations`: trigger producer (partitioned theo ngày)
- [ ] `dbt_models`: `@dbt_assets` decorator → tự sinh asset cho mỗi model
- [ ] `pipeline_health_check`: check row counts, lag
- [ ] `partitions_cleanup` (Phase 11): drop partition cũ
- [ ] `clickhouse_backup` (Phase 10): trigger backup

**C. Sensors**:

- [ ] `kafka_consumer_lag_sensor`: alert nếu lag > threshold
- [ ] `freshness_sensor`: check SLA freshness (data trong marts < 1h cũ)
- [ ] `dbt_test_failure_sensor`: alert khi dbt test fail

**D. Schedules (BẮT BUỘC, theo chuẩn DE)**:

| Schedule                      | Cron            | Job                     | Mục đích                           |
| ----------------------------- | --------------- | ----------------------- | ------------------------------------- |
| `streaming_health_5min`     | `*/5 * * * *` | health check            | Phát hiện ingestion stop sớm       |
| `dbt_staging_hourly`        | `0 * * * *`   | dbt run stg + int       | Refresh layer cao tần                |
| `dbt_marts_hourly`          | `15 * * * *`  | dbt run marts           | Lệch 15 phút để chờ staging xong |
| `dbt_test_full_daily`       | `0 2 * * *`   | dbt test --full         | 2h sáng, low traffic                 |
| `clickhouse_backup_daily`   | `0 3 * * *`   | backup full             | 3h sáng                              |
| `partitions_cleanup_weekly` | `0 4 * * 0`   | drop partitions cũ     | Chủ nhật 4h sáng                   |
| `compaction_status_daily`   | `30 5 * * *`  | check `system.merges` | Monitor MergeTree health              |

- [ ] UI accessible tại `localhost:3002`

**Acceptance Criteria**:

- `dagster dev` start OK
- Asset graph hiển thị full lineage raw → marts → ops
- Tất cả schedules visible trong UI, có thể manually trigger
- Sensor evaluate được mà không crash

**Commit point** (chia nhỏ):

- `feat(dagster): init Dagster project with resources for clickhouse kafka dbt`
- `feat(dagster): add ingestion and dbt assets with auto lineage`
- `feat(dagster): add sensors for kafka lag, freshness, dbt failures`
- `feat(dagster): add schedules for hourly/daily/weekly maintenance jobs`

---

### PHASE 7 — GRAFANA REAL-TIME MONITORING + ALERTING

**Mục tiêu**: dashboard real-time + alert rules cho pipeline.

**Deliverables**:

**A. Dashboards**:

- [ ] `pipeline-realtime.json`:

| Panel                         | Query                                                                                                                                        | Refresh |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| Total rows streaming          | `SELECT count() FROM noaa_raw.observations_streaming`                                                                                      | 5s      |
| Ingestion rate (rows/s, 1min) | `SELECT count()/60 FROM noaa_raw.observations_streaming WHERE _ingested_at > now() - INTERVAL 60 SECOND`                                   | 5s      |
| Ingestion timeline (5min)     | `SELECT toStartOfSecond(_ingested_at) AS t, count() FROM ... GROUP BY t ORDER BY t`                                                        | 5s      |
| Kafka consumer lag            | `SELECT topic, partition, current_offset, num_messages_read FROM system.kafka_consumers`                                                   | 5s      |
| Latest offset per partition   | `SELECT _kafka_partition, max(_kafka_offset) FROM ... GROUP BY _kafka_partition`                                                           | 5s      |
| Avg insert latency            | `SELECT avg(query_duration_ms) FROM system.query_log WHERE query_kind='Insert' AND event_time > now() - INTERVAL 5 MINUTE`                 | 10s     |
| Rows per partition            | `SELECT partition, sum(rows) FROM system.parts WHERE database='noaa_raw' AND table='observations_streaming' AND active GROUP BY partition` | 30s     |
| Disk usage by table           | `SELECT table, formatReadableSize(sum(bytes_on_disk)) FROM system.parts WHERE database LIKE 'noaa_%' AND active GROUP BY table`            | 60s     |
| Data freshness (mart)         | `SELECT now() - max(updated_at) FROM noaa_marts.mart_ingestion_metrics`                                                                    | 30s     |

- [ ] `clickhouse-system.json`:
  - CPU/memory (`system.metrics`, `system.asynchronous_metrics`)
  - Top slow queries (`system.query_log`)
  - Merge activity (`system.merges`)
  - Mutations (`system.mutations`)
  - Replication queue (`system.replication_queue`) — không có data nhưng giữ panel cho hợp pattern prod

**B. Alerting (MỚI, theo 6.7)**:

- [ ] Contact point: webhook (default dummy URL, document cách đổi sang Slack/Discord trong RUNBOOK)
- [ ] Alert rules trong `docker/grafana/provisioning/alerting/rules.yml`:

| Alert                     | Condition                                              | Severity |
| ------------------------- | ------------------------------------------------------ | -------- |
| `IngestionStalled`      | rows/s = 0 trong 5 phút khi producer đáng lẽ chạy | critical |
| `KafkaLagHigh`          | consumer lag > 1M messages                             | warning  |
| `ClickHouseDiskFull`    | disk usage > 80%                                       | critical |
| `ClickHouseDiskWarning` | disk usage > 60%                                       | warning  |
| `DataStaleness`         | `mart_ingestion_metrics` cũ > 2h                    | warning  |
| `MergeQueueBacked`      | `system.merges` > 50 hàng                           | warning  |

- [ ] Mỗi alert có annotation link tới section trong `RUNBOOK.md`

**Acceptance Criteria**:

- `http://localhost:3000` → dashboards thấy số đếm tăng khi producer chạy
- Tắt producer → "Ingestion rate" = 0 trong dashboard
- Force điều kiện alert (giảm threshold xuống 0) → alert fire trong Grafana UI
- Không panel nào lỗi datasource

**Commit point**:

- `feat(grafana): add realtime pipeline and clickhouse system dashboards`
- `feat(grafana): add alert rules with webhook contact point and runbook links`

---

### PHASE 8 — METABASE BI DASHBOARDS

**Mục tiêu**: dashboards business-facing trên marts.

**Deliverables**:

- [ ] Init Metabase: admin user, connect ClickHouse (DB: `noaa_marts`)
- [ ] Questions:
  1. **Global Temperature Trend (1900-now)**: line chart
  2. **Top 20 Hottest Stations all-time**: bar chart
  3. **Top 20 Coldest Stations**: tương tự
  4. **Annual Precipitation by Country (top 20)**: bar chart
  5. **Extreme Weather Events Timeline**: scatter
  6. **Climate Change Indicator**: so sánh 1950s vs 2010s, geo map
  7. **Snow Coverage Decline**: line chart với anomaly
  8. **Stations by Country (geo)**: pin map
- [ ] Dashboards:
  - "Global Climate Overview" (Q1, Q6, Q7, Q8)
  - "Station Records" (Q2, Q3, Q5)
  - "Country Insights" (Q4, Q8)
- [ ] Export JSON vào `reporting/metabase/dashboards/exported/`
- [ ] README hướng dẫn import

**Acceptance Criteria**:

- `http://localhost:3001` → thấy 3 dashboards
- Mỗi dashboard load < 10s
- Có ≥ 1 visualization dạng map

**Commit point**: `feat(metabase): add 3 BI dashboards on climate marts with exported JSON`

---

### PHASE 9 — SQL PLAYGROUND WEB (MỚI)

**Mục tiêu**: web nội bộ mô phỏng SQL Playground của ClickHouse, có sẵn các query mẫu để học và benchmark.

#### 9.1. Architecture

```
Browser
   │ HTMX requests
   ▼
FastAPI (Python)
   ├── GET /              → Trang chính (HTML từ Jinja2)
   ├── GET /queries       → List queries (sidebar)
   ├── GET /queries/{id}  → Load query nội dung vào editor
   ├── POST /execute      → Chạy query, trả về HTML partial (table)
   ▼
clickhouse-connect (Python driver)
   ▼
ClickHouse (cluster local)
```

**Tech choice**:

- **FastAPI** (backend) — Python, async, đúng stack DE
- **Jinja2** (templating) — server-side render
- **HTMX** (frontend interactivity) — không cần build pipeline, không React
- **Monaco Editor** (CDN) — same editor như VSCode, hỗ trợ SQL syntax
- **Pico CSS** (CDN) — minimal CSS

#### 9.2. UI Layout (giống ảnh 2)

```
┌─────────────────────────────────────────────────────────────────┐
│ NOAA SQL Playground                              [GitHub link]   │
├──────────────┬──────────────────────────────────────────────────┤
│ DATABASES    │ Query: "Average precipitation per year"  [Save]  │
│ ▼ noaa_raw   │ ┌──────────────────────────────────────────────┐│
│   - obs_*    │ │ SELECT year, avg(precipitation) AS ...        ││
│   - stations │ │ FROM noaa.observations                        ││
│ ▼ noaa_marts │ │ WHERE date > '1970-01-01' AND code IN (...)   ││
│              │ └──────────────────────────────────────────────┘│
│ QUERIES      │  [Run]  Ctrl+Enter                              │
│ ▼ Analytics  ├──────────────────────────────────────────────────┤
│  - avg_pre.. │ Query time: 0.662s    Rows read: 889,105,425    │
│  - high_tmp. │ Bytes read: 12.3 GB   Rows/s: 1.3B   Bytes/s: ..│
│ ▼ Benchmarks ├──────────────────────────────────────────────────┤
│  - codec_v1  │ Results | Charts                                 │
│  - codec_v2  │ ┌───┬────────────┬──────────────┬──────────────┐│
│ ▼ Ops        │ │ # │ year       │ avg_precip   │ country      ││
│  - count_all │ │ 1 │ 1970-01-01 │ 55.001...    │ Albania      ││
│  - show_tbl  │ │ 2 │ 1971-01-01 │ 40.810...    │ Albania      ││
└──────────────┴──────────────────────────────────────────────────┘
```

#### 9.3. Predefined Queries (lấy từ ClickHouse playground)

Mỗi query là 1 file YAML trong `playground/queries/<category>/<name>.yaml`:

```yaml
# playground/queries/analytics/avg_precipitation_by_country.yaml
name: "Average precipitation per year by country"
description: |
  Calculates the average annual precipitation by country using data
  from the NOAA after 1970, excluding specified country codes.
category: analytics
tags: [precipitation, country, yearly, dictionary]
sql: |
  SELECT 
      toYear(date) AS year,
      avg(precipitation) AS avg_precipitation,
      dictGet('country.country_iso_codes', 'name', code) AS country
  FROM noaa_marts.mart_observations_enriched
  WHERE date > '1970-01-01'
    AND code IN ('AL','AN','AU','BE','BO','CY','DA','EI','EZ','EN',
                 'FI','FR','GG','GI','GK','GM','GR','HR','HU','IC',
                 'IM','IT','JE','LG','LH','LO','LS','LU','MD','MK',
                 'MN','MT','NL','NO','PL','PO','RO','SI','SM','SP',
                 'SW','SZ','TU','UK','UP','VT')
  GROUP BY year, country
  ORDER BY country, year
```

**Danh sách query bắt buộc** (lấy theo ảnh + blog):

**`analytics/`**:

- `avg_precipitation_by_country.yaml`
- `highest_temp_in_portugal.yaml` (baseline)
- `highest_temp_in_portugal_subquery.yaml`
- `highest_temp_in_portugal_join.yaml`
- `highest_temp_in_portugal_dict_unopt.yaml`
- `highest_temp_in_portugal_dict_opt.yaml`
- `highest_temp_world.yaml`
- `highest_temp_canadian_regions.yaml`
- `highest_temp_portuguese_regions.yaml`
- `hottest_areas_us_mexico.yaml`
- `find_best_holiday_conditions.yaml`
- `group_locations_by_temperature.yaml`

**`benchmarks/`** (so sánh codecs):

- `columns_size_codec_v1.yaml` — không codec
- `columns_size_codec_v2.yaml` — LZ4
- `columns_size_codec_v3.yaml` — ZSTD
- `columns_size_codec_v4.yaml` — Delta + ZSTD
- `columns_size_codec_optimal.yaml` — tối ưu per column
- `table_size_codec_v1.yaml` ... `v4.yaml`
- `most_effective_codec_per_column.yaml`

**`ops/`**:

- `count_all_rows.yaml`
- `show_tables.yaml`
- `min_max_boundaries.yaml`
- `stations_no_precipitation.yaml`
- `select_one_entry_from_dict.yaml`

> Query SQL chi tiết: copy từ ClickHouse blog (https://clickhouse.com/blog/real-world-data-noaa-climate-data) và playground. Adjust tên bảng cho khớp schema của ta.

#### 9.4. Implementation

**`playground/app/main.py`** (skeleton):

```python
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .clickhouse_client import execute_query
from .query_loader import load_all_queries, get_query

app = FastAPI(title="NOAA SQL Playground")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    queries = load_all_queries()
    return templates.TemplateResponse("index.html", {
        "request": request, "queries": queries
    })

@app.get("/queries/{query_id}", response_class=HTMLResponse)
async def load_query(query_id: str, request: Request):
    query = get_query(query_id)
    return templates.TemplateResponse("partials/editor_content.html", {
        "request": request, "query": query
    })

@app.post("/execute", response_class=HTMLResponse)
async def run_query(request: Request, sql: str = Form(...)):
    result = await execute_query(sql)
    return templates.TemplateResponse("partials/result_table.html", {
        "request": request, "result": result
    })
```

**`playground/app/clickhouse_client.py`**:

```python
import time
import clickhouse_connect
from .models import QueryResult

def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username=os.getenv("CLICKHOUSE_USER"),
        password=os.getenv("CLICKHOUSE_PASSWORD"),
    )

async def execute_query(sql: str) -> QueryResult:
    client = get_client()
    start = time.time()
    result = client.query(sql, settings={
        'max_execution_time': int(os.getenv("PLAYGROUND_QUERY_TIMEOUT_SEC", 30)),
        'max_result_rows': int(os.getenv("PLAYGROUND_MAX_ROWS", 10000)),
    })
    elapsed = time.time() - start
    return QueryResult(
        columns=result.column_names,
        rows=result.result_rows,
        query_time_sec=elapsed,
        rows_read=result.summary.get('read_rows', 0),
        bytes_read=result.summary.get('read_bytes', 0),
    )
```

**Security notes** (BẮT BUỘC):

- Tạo user ClickHouse riêng `playground_readonly` với `readonly=1`
- Set `PLAYGROUND_QUERY_TIMEOUT_SEC=30`, `PLAYGROUND_MAX_ROWS=10000`
- Không cho `DROP`, `ALTER`, `INSERT` (readonly user xử lý)
- Rate limit per IP (optional, dùng `slowapi`)

**Service trong docker-compose** (Phase 1 sau đó update, hoặc add Phase 9):

```yaml
  playground:
    build: ../playground
    ports: ["8080:8080"]
    environment:
      CLICKHOUSE_HOST: clickhouse
      CLICKHOUSE_USER: playground_readonly
      CLICKHOUSE_PASSWORD: ${PLAYGROUND_RO_PASSWORD}
    depends_on:
      clickhouse:
        condition: service_healthy
```

**Acceptance Criteria**:

- `http://localhost:8080` mở trang chính
- Sidebar list ≥ 25 queries grouped by category
- Click query → load SQL vào editor
- Click Run → trả về kết quả < 30s
- Hiển thị: Query time, Rows read, Bytes read, Rows/s, Bytes/s
- Test 1 query "Highest temperature in Portugal" so sánh 5 variant → thấy rõ chênh lệch performance
- Readonly user không INSERT được (test: gửi `INSERT INTO test VALUES (1)` → error)

**Commit point** (chia nhỏ):

- `feat(playground): scaffold FastAPI app with Jinja2 and HTMX`
- `feat(playground): implement ClickHouse query execution with stats`
- `feat(playground): add 25+ predefined queries from NOAA blog`
- `feat(playground): integrate Monaco editor with SQL syntax highlighting`
- `infra(docker): add playground service with readonly user`

---

### PHASE 10 — BACKUP & DISASTER RECOVERY (MỚI)

**Mục tiêu**: backup ClickHouse theo chuẩn DE, có thể restore khi cần.

#### 10.1. Tool: `clickhouse-backup`

[github.com/Altinity/clickhouse-backup](https://github.com/Altinity/clickhouse-backup) là de-facto tool.

Capabilities:

- Full backup, incremental backup
- Backup to local disk hoặc S3-compatible
- Restore từng table, partition, hoặc full DB
- Schedule qua cron hoặc external orchestrator

#### 10.2. Deliverables

- [ ] Add `clickhouse-backup` service vào docker-compose (sidecar pattern):

  ```yaml
  clickhouse-backup:
    image: altinity/clickhouse-backup:2.5
    volumes:
      - ./clickhouse/data:/var/lib/clickhouse
      - ../backup/storage:/backups
      - ../backup/clickhouse-backup-config.yml:/etc/clickhouse-backup/config.yml
    depends_on:
      clickhouse: { condition: service_healthy }
    command: server
    ports: ["7171:7171"]   # API
  ```
- [ ] `backup/clickhouse-backup-config.yml`:

  ```yaml
  general:
    remote_storage: none   # local for now
    backups_to_keep_local: 7
    backups_to_keep_remote: 30
  clickhouse:
    host: clickhouse
    username: default
    password: ${CLICKHOUSE_PASSWORD}
    sync_replicated_tables: false
  ```
- [ ] Scripts:

  - `backup/scripts/backup_full.sh`: full backup → tar.gz
  - `backup/scripts/backup_incremental.sh`: incremental
  - `backup/scripts/restore.sh`: restore từ backup name
  - `backup/scripts/verify_backup.sh`: count rows, validate
- [ ] Dagster job `backup_job.py` chạy theo schedule `clickhouse_backup_daily` (Phase 6)
- [ ] `backup/retention_policy.md`:

  - **RPO**: 24h (chấp nhận mất tối đa 1 ngày data)
  - **RTO**: 1h (khôi phục được trong 1 giờ)
  - Full backup: hàng ngày 3h sáng
  - Incremental: mỗi 6h (optional)
  - Retention: 7 ngày local, 30 ngày remote (khi có S3)
  - Restore drill: ít nhất 1 lần/tháng (manual)
- [ ] Update `RUNBOOK.md` thêm scenario "How to restore from backup"

#### 10.3. Restore drill (BẮT BUỘC test trong phase)

Steps để verify:

1. Note count hiện tại: `SELECT count() FROM noaa_marts.mart_global_temperature_yearly`
2. Run full backup: `./backup/scripts/backup_full.sh test_backup_1`
3. Drop table: `DROP TABLE noaa_marts.mart_global_temperature_yearly`
4. Verify mất: count → error table not exist
5. Restore: `./backup/scripts/restore.sh test_backup_1 noaa_marts.mart_global_temperature_yearly`
6. Verify count khớp với step 1
7. Document kết quả + thời gian trong `RUNBOOK.md`

**Acceptance Criteria**:

- `clickhouse-backup list` ra ít nhất 1 backup
- Backup file tồn tại trong `backup/storage/`
- Restore drill (steps trên) thành công, RTO < 1h
- `RUNBOOK.md` có section "Restore Procedure" hoàn chỉnh

**Commit point**:

- `feat(backup): add clickhouse-backup service with config`
- `feat(backup): add backup/restore scripts and retention policy`
- `feat(dagster): integrate daily backup job into schedules`
- `docs(runbook): document restore procedure with verified drill results`

---

### PHASE 11 — DATA LIFECYCLE (TTL & RETENTION) (MỚI)

**Mục tiêu**: tự động drop dữ liệu cũ theo retention policy — chuẩn DE để controll cost.

#### 11.1. ClickHouse TTL

**Chiến lược**:

- `noaa_raw.observations_streaming`: giữ 90 ngày (mục đích raw debug)
- `noaa_raw.observations_historical`: giữ vĩnh viễn (data lịch sử)
- `noaa_marts.*`: giữ vĩnh viễn (đã aggregate, nhỏ)
- `system.query_log`: TTL 7 ngày (built-in setting)
- Bảng DLQ: TTL 30 ngày

#### 11.2. Deliverables

- [ ] `ALTER TABLE noaa_raw.observations_streaming MODIFY TTL date + INTERVAL 90 DAY;`
- [ ] `ALTER TABLE noaa_raw.observations_dlq MODIFY TTL _ingested_at + INTERVAL 30 DAY;`
- [ ] Setting `system.query_log` TTL trong `docker/clickhouse/config.d/logging.xml`:
  ```xml
  <query_log>
      <database>system</database>
      <table>query_log</table>
      <engine>Engine = MergeTree PARTITION BY toYYYYMM(event_date) TTL event_date + INTERVAL 7 DAY</engine>
  </query_log>
  ```
- [ ] Asset `partitions_cleanup` trong Dagster (`orchestration/.../assets/lifecycle.py`):
  - Check `system.parts` cho partitions cũ ngoài TTL
  - Force optimize: `OPTIMIZE TABLE ... FINAL`
  - Log số partition dropped
- [ ] Schedule `partitions_cleanup_weekly` (đã định nghĩa Phase 6)
- [ ] Kafka topic retention: set `retention.ms=604800000` (7 ngày) cho `noaa.observations`

#### 11.3. Storage Tiering (Nice-to-have, không bắt buộc)

ClickHouse hỗ trợ multi-disk storage policy:

- Hot tier: data < 30 ngày trên SSD
- Cold tier: data > 30 ngày trên HDD (local mock)

Config trong `docker/clickhouse/config.d/storage.xml`. Document trong `ARCHITECTURE.md`, nói rõ "production setup, demo chỉ enable nếu user yêu cầu".

**Acceptance Criteria**:

- `SHOW CREATE TABLE noaa_raw.observations_streaming` cho thấy TTL clause
- `SELECT * FROM system.parts WHERE table='observations_streaming' AND min_date < today() - 90` → 0 rows sau khi cleanup chạy
- Dagster job `partitions_cleanup` run thành công, log số partition đã drop
- Kafka `kafka-configs.sh --describe --entity-type topics --entity-name noaa.observations` cho thấy retention.ms = 7 days

**Commit point**:

- `feat(lifecycle): add TTL policies for raw streaming and DLQ tables`
- `feat(lifecycle): add partitions_cleanup Dagster asset with weekly schedule`
- `infra(kafka): set topic retention policy`

---

### PHASE 12 — CI/CD & QUALITY GATES (MỚI)

**Mục tiêu**: tự động lint, parse, test ở mỗi push — chuẩn DE production.

#### 12.1. GitHub Actions

- [ ] `.github/workflows/ci.yml`:

  ```yaml
  name: CI
  on: [push, pull_request]
  jobs:
    lint-python:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: '3.11' }
        - run: pip install ruff mypy
        - run: ruff check .
        - run: ruff format --check .

    dbt-parse:
      runs-on: ubuntu-latest
      services:
        clickhouse:
          image: clickhouse/clickhouse-server:24.10
          ports: ["8123:8123", "9000:9000"]
          options: --health-cmd "wget --spider -q http://localhost:8123/ping || exit 1"
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: '3.11' }
        - run: pip install dbt-clickhouse
        - working-directory: transform
          run: |
            cp profiles.yml.example profiles.yml
            dbt deps
            dbt parse

    sql-lint:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: '3.11' }
        - run: pip install sqlfluff
        - run: sqlfluff lint transform/models/ --dialect clickhouse

    yaml-validation:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - run: pip install yamllint
        - run: yamllint playground/queries/ docker/grafana/provisioning/
  ```
- [ ] `.github/workflows/nightly-backup.yml` (optional, chỉ chạy nếu repo có S3 secrets)

#### 12.2. Pre-commit hooks

- [ ] `.pre-commit-config.yaml`:

  ```yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.7.0
      hooks:
        - id: ruff
        - id: ruff-format
    - repo: https://github.com/sqlfluff/sqlfluff
      rev: 3.2.0
      hooks:
        - id: sqlfluff-lint
          args: ["--dialect", "clickhouse"]
    - repo: https://github.com/Yelp/detect-secrets
      rev: v1.5.0
      hooks:
        - id: detect-secrets
  ```
- [ ] Document trong README cách install: `pre-commit install`

#### 12.3. Quality Gates trong dbt

- [ ] `transform/dbt_project.yml`:
  ```yaml
  tests:
    +severity: error      # Mặc định fail = error
    +store_failures: true  # Store row fail vào ClickHouse để debug
  ```

**Acceptance Criteria**:

- Push 1 commit có ruff error → CI fail
- Push commit clean → CI pass tất cả 4 jobs
- `pre-commit run --all-files` pass local
- Badge CI hiển thị trong README

**Commit point**:

- `infra(ci): add github actions for lint dbt-parse sql-lint yaml-validation`
- `infra(ci): add pre-commit hooks for python sql secrets`

---

### PHASE 13 — E2E TEST & DOCS HOÀN THIỆN

**Mục tiêu**: chạy thử pipeline đầu-cuối, hoàn thiện docs.

**Deliverables**:

- [ ] `tests/e2e/test_pipeline_end_to_end.py`: smoke test:

  1. Setup infra (`docker compose up`)
  2. Backfill 1M rows (subset test)
  3. Run producer 30s với rate giảm
  4. Verify ClickHouse rows tăng
  5. Run `dbt build`
  6. Verify marts có data
  7. Query Grafana datasource API
  8. Hit playground endpoint `/execute` với 1 query
  9. Trigger backup → verify file
  10. Cleanup
- [ ] `README.md` complete:

  - Architecture diagram
  - Prerequisites (Docker, Python 3.11, uv, ~50GB disk free)
  - Quick start (5 lệnh: clone, env setup, docker up, bootstrap, open dashboards)
  - Port map table
  - Troubleshooting
  - Screenshots
  - CI badge
- [ ] `ARCHITECTURE.md`: trade-offs, ADRs cho mỗi quyết định lớn
- [ ] `RUNBOOK.md` đầy đủ ≥ 7 scenarios:

  1. Pipeline ingestion stopped
  2. Kafka consumer lag too high
  3. Disk full on ClickHouse
  4. dbt test failure investigation
  5. Restore from backup
  6. How to backfill a specific year
  7. How to add a new dbt model
- [ ] `SLA.md` finalized với metrics đã đo thực tế
- [ ] dbt docs build & screenshot lineage

**Acceptance Criteria**:

- Người mới clone + đọc README → chạy được pipeline < 30 phút
- E2E test pass
- `ruff check .` không error
- Tất cả docs cross-link nhau hợp lý

**Commit point**:

- `test(e2e): add end-to-end pipeline smoke test`
- `docs: complete README ARCHITECTURE RUNBOOK SLA with screenshots`

---

## 8. QUY TẮC THỰC THI CHO AGENT

### 8.1. Trước khi bắt đầu MỖI phase

1. Đọc lại section của phase trong PLAN.md
2. Check Acceptance Criteria phase TRƯỚC. Chưa pass → quay lại fix
3. Tạo TODO list nội bộ
4. Đọc `RUNBOOK.md` để biết cách xử lý nếu gặp lỗi quen thuộc

### 8.2. Khi gặp lỗi

- **Lỗi config/typo**: tự fix, commit `fix(<scope>): ...`, tiếp tục
- **Lỗi data/network**: log lỗi, fallback dataset nhỏ hơn, document trong README
- **Lỗi kiến trúc**: KHÔNG sửa silently. Document trade-off trong `ARCHITECTURE.md`, commit `docs(arch): document <limitation>`
- **Lỗi không tự fix sau 3 lần**: dừng, ghi rõ trong commit, để user can thiệp

### 8.3. Khi nào HỎI user (không tự quyết)

- Remote URL khác với spec
- Cần API key thật (vd: Slack webhook cho alert)
- Quyết định lớn về tool (vd: dataset không truy cập được)

### 8.4. Cấm tuyệt đối

- ❌ Commit `.env`, `data/`, file > 50MB, password
- ❌ Push khi acceptance criteria chưa pass
- ❌ Sửa PLAN.md mà không note rõ trong commit `docs(plan): revise phase X — <lý do>`
- ❌ Gộp 2 phase vào 1 commit
- ❌ Hardcode credentials
- ❌ Dùng `latest` tag cho Docker image production-relevant
- ❌ Skip Acceptance Criteria
- ❌ Tạo bảng ClickHouse không có TTL nếu phase 11 đã chạy
- ❌ Tạo dbt model không có schema test

### 8.5. Mẫu workflow cho 1 chức năng nhỏ

```
1. Đọc deliverable cần làm
2. Code (tuân thủ DE standards section 6)
3. Test thủ công (chạy lệnh, check output)
4. Nếu OK:
   git add <files>
   git commit -m "<type>(<scope>): <subject>"
   git push origin main
5. Update TODO list trong phase
```

---

## 9. CHECKLIST FINAL TRƯỚC KHI TUYÊN BỐ DỰ ÁN XONG

### Infrastructure

- [ ] `docker compose up -d` clean trên máy mới
- [ ] `make bootstrap` setup full trong 1 lệnh
- [ ] Tất cả services healthy: ClickHouse, Kafka, Grafana, Metabase, Playground

### Data

- [ ] ClickHouse có ≥ 1B rows historical
- [ ] Producer đạt ≥ 200K rows/s (chấp nhận, target 1M)
- [ ] Streaming observations đang chảy
- [ ] dbt `build` không failed test
- [ ] Marts đầy đủ data

### Orchestration

- [ ] Dagster UI hiển thị full lineage
- [ ] Tất cả schedules visible và có thể trigger
- [ ] Sensors evaluate không crash

### Monitoring

- [ ] Grafana dashboard realtime cập nhật khi producer chạy
- [ ] Alert rules configured và test fire được
- [ ] Metabase 3 dashboards có data thật

### Web & Tools

- [ ] SQL Playground accessible, có ≥ 25 queries
- [ ] Test so sánh codec V1 vs optimal thấy chênh lệch
- [ ] Test 5 variant query Portugal thấy chênh performance

### Backup & DR

- [ ] `clickhouse-backup` chạy hàng ngày qua Dagster
- [ ] Restore drill đã thực hiện và document trong RUNBOOK
- [ ] RPO/RTO định nghĩa trong `retention_policy.md`

### Lifecycle

- [ ] TTL applied cho streaming + DLQ + query_log
- [ ] Kafka topic retention set
- [ ] Cleanup job chạy weekly

### Quality

- [ ] CI pass: lint + dbt parse + sql lint + yaml validation
- [ ] Pre-commit hooks works local
- [ ] dbt tests pass ≥ 90%
- [ ] E2E smoke test pass

### Docs

- [ ] README đầy đủ với screenshots
- [ ] ARCHITECTURE.md có ADRs
- [ ] RUNBOOK.md có ≥ 7 scenarios
- [ ] SLA.md với SLO measurable
- [ ] dbt docs build được

### Git

- [ ] Mọi phase đều có commit + push
- [ ] Không có file `.env`, data, secret trong git history
- [ ] Tất cả commit theo Conventional Commits

---

## 10. RỦI RO VÀ MITIGATION

| Rủi ro                                      | Khả năng    | Mitigation                                                      |
| -------------------------------------------- | ------------- | --------------------------------------------------------------- |
| 1M rows/s không đạt trên laptop          | Cao           | Hạ target ~200K, document rõ                                  |
| NOAA S3 link đổi                           | Trung bình   | Fallback: ClickHouse Cloud demo dataset                         |
| Disk đầy khi load 1B rows                  | Cao           | ZSTD compression, check free space, giảm xuống 500M nếu cần |
| ClickHouse OOM khi dbt mart lớn             | Trung bình   | Dùng `materialized='incremental'`                            |
| Conflict port                                | Thấp         | Mọi port khai báo trong `.env`                              |
| Playground bị abuse query nặng             | Thấp (local) | `readonly` user, timeout 30s, max_rows 10K                    |
| Backup file quá lớn                        | Trung bình   | Incremental backup, retention policy                            |
| Kafka không sync sau restart container      | Trung bình   | Health check + retry logic trong producer                       |
| Schedule conflict (dbt run khi backup chạy) | Trung bình   | Stagger schedules (xem bảng Phase 6.D)                         |
| Pre-commit chậm                             | Thấp         | Chỉ chạy ruff + format ở pre-commit, full check ở CI        |

---

## 11. SLOGAN CHO AGENT

> **"Code small, test it, commit it, push it. Backup it. Document it. Move on."**

> Khi nghi ngờ: ưu tiên **observable** hơn **clever**. Ưu tiên **recoverable** hơn **fast**.

> Mỗi quyết định trade-off → ghi vào `ARCHITECTURE.md`. Mỗi incident → ghi vào `RUNBOOK.md`.

---

**Hết kế hoạch v2. Bắt đầu từ Phase 0.**
