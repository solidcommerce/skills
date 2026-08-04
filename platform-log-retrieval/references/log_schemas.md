# Log Schemas Reference

Detailed schemas for all log formats across the three backends.

## Table of Contents
- [Normalized Output Schema](#normalized-output-schema)
- [AppLogRecord (Blob NDJSON)](#applogrecord-blob-ndjson)
- [RrLogRecord (Blob NDJSON)](#rrlogrecord-blob-ndjson)
- [NLog CSV Format (SMB/Windows Services)](#nlog-csv-format)
- [SQL appslogs Table](#sql-appslogs-table)
- [SQL weblogs Table](#sql-weblogs-table)
- [SQL RequestResponseLogs Table](#sql-requestresponselogs-table)
- [Other SQL Tables](#other-sql-tables)

---

## Normalized Output Schema

All scripts normalize their output to this common structure:

### Metadata Header
```json
{
  "source": "blob|sql|smb",
  "container_or_table": "services-logs|appslogs|LDS_Services|...",
  "query_filters": {
    "date": "2026-04-02",
    "service": "...",
    "level": "Error",
    "company_id": 12345,
    "keyword": "failed"
  },
  "total_results": 42,
  "truncated": false,
  "skipped_entries": 0,
  "query_time_ms": 1234
}
```

### Entry Schema
```json
{
  "source": "blob|sql|smb",
  "container_or_table": "string",
  "timestamp": "ISO 8601 datetime",
  "level": "Error|Warning|Info|Debug|Trace|unknown",
  "service_name": "string",
  "server_name": "string",
  "company_id": "number|null",
  "short_description": "string",
  "long_description": "string|null",
  "request": "string|null",
  "response": "string|null",
  "thread_id": "number|null",
  "raw_line": "string|null (original unparsed line for free-text logs)"
}
```

### Level Normalization

Map all source-specific levels to these canonical values:

| Source Value | Normalized |
|-------------|-----------|
| Error, ERROR, error, 1 | Error |
| Warning, WARN, warn, 2 | Warning |
| Info, INFO, info, Information, 3 | Info |
| Debug, DEBUG, debug, 4 | Debug |
| Trace, TRACE, trace, Verbose, 5 | Trace |
| (anything else) | unknown |

---

## AppLogRecord (Blob NDJSON)

Found in: `services-logs`, `web-logs`, `openretail/applogs` containers.

Each line in the NDJSON file is one record:

```json
{
  "CompanyId": 12345,
  "ApplicationId": 100,
  "LogDateTime": "2026-04-02T14:30:00",
  "ServerName": "scservices1",
  "LogType": "Error",
  "Level": "Error",
  "ShortDescription": "Order import failed",
  "LongDescription": "Full stack trace or detailed error message",
  "ThreadId": 42
}
```

### Field Mapping to Normalized Schema

| AppLogRecord Field | Normalized Field | Notes |
|-------------------|-----------------|-------|
| LogDateTime | timestamp | Parse as ISO 8601 |
| Level or LogType | level | Prefer Level, fall back to LogType |
| ServerName | server_name | |
| CompanyId | company_id | |
| ShortDescription | short_description | |
| LongDescription | long_description | |
| ThreadId | thread_id | |
| ApplicationId | (metadata) | Used for filtering, not in normalized output |

### AppFallback Variant

In `services-logs` container, the sub-type is often `AppFallback`. Same schema as AppLogRecord but may have additional or missing fields. Parse defensively.

---

## RrLogRecord (Blob NDJSON)

Found in: `openretail/rrlogs`, some `web-logs` containers.

```json
{
  "CompanyId": 12345,
  "ApplicationId": 100,
  "LogDateTime": "2026-04-02T14:30:00",
  "ServerName": "scservices1",
  "Request": "<XML or JSON request body>",
  "Response": "<XML or JSON response body>",
  "ThreadId": 42
}
```

### Field Mapping to Normalized Schema

| RrLogRecord Field | Normalized Field | Notes |
|------------------|-----------------|-------|
| LogDateTime | timestamp | |
| ServerName | server_name | |
| CompanyId | company_id | |
| Request | request | Full request payload (XML or JSON) |
| Response | response | Full response payload |
| ThreadId | thread_id | |
| (none) | level | Set to "Info" (RR logs don't have levels) |
| (none) | short_description | Generate from request type/method if possible |

---

## NLog CSV Format

Found on: SMB network share (Windows Service logs before blob upload).

**Tab-delimited** with these columns in order:

```
logDateTime	level	serverName	logType	IntegrationName	ServiceName	InternalCustomerId	SolidCommercecompanyId	shortDescription	longDescription	Request	Response
```

### Column Index Mapping

| Index | Column | Normalized Field | Notes |
|-------|--------|-----------------|-------|
| 0 | logDateTime | timestamp | Various datetime formats |
| 1 | level | level | Error, Warning, Info, etc. |
| 2 | serverName | server_name | |
| 3 | logType | (metadata) | Log category |
| 4 | IntegrationName | service_name | Integration identifier |
| 5 | ServiceName | service_name | Service name (prefer this over IntegrationName) |
| 6 | InternalCustomerId | (metadata) | Internal customer reference |
| 7 | SolidCommercecompanyId | company_id | Parse as integer |
| 8 | shortDescription | short_description | |
| 9 | longDescription | long_description | |
| 10 | Request | request | |
| 11 | Response | response | |

### Parsing Notes

- Columns may be missing if the line is shorter than expected — handle gracefully
- Tab character is the delimiter, but field values may contain newlines within quotes
- Some services use a simplified format with fewer columns
- The file may have no header row — detect by checking if first line matches datetime pattern

---

## SQL appslogs Table

Found in: `SCServicesLogs` database on `172.179.2.207`.

| Column | Type | Nullable | Normalized Field |
|--------|------|----------|-----------------|
| LogDateTime | datetime | No | timestamp |
| Application | int | No | service_name (as string) |
| MessageType | int | Yes | level (see mapping below) |
| ShortDescription | varchar(500) | Yes | short_description |
| HostName | varchar(100) | Yes | server_name |
| LongDescription | nvarchar(max) | Yes | long_description |
| LogType | varchar(50) | Yes | level (alternative) |
| ThreadId | int | Yes | thread_id |
| ThreadName | nvarchar(250) | Yes | (metadata) |
| CompanyId | int | Yes | company_id |

### MessageType to Level Mapping

| MessageType | Level |
|------------|-------|
| 1 | Error |
| 2 | Warning |
| 3 | Info |
| 4 | Debug |
| 5 | Trace |

When both MessageType and LogType are present, prefer LogType (string) for the normalized level.

---

## SQL weblogs Table

| Column | Type | Nullable | Normalized Field |
|--------|------|----------|-----------------|
| LogDateTime | datetime | No | timestamp |
| ApplicationID | int | No | service_name (as string) |
| CallerIP | varchar(50) | Yes | (extra field) |
| RequestedMethod | varchar(255) | Yes | short_description |
| Notes | varchar(500) | Yes | long_description |
| HostName | varchar(500) | Yes | server_name |
| CompanyID | int | Yes | company_id |
| SeatID | int | Yes | (extra field) |
| DeveloperID | int | Yes | (extra field) |

Note the column name differences from appslogs:
- `ApplicationID` (not `Application`)
- `CompanyID` (not `CompanyId`)

---

## SQL RequestResponseLogs Table

| Column | Type | Notes |
|--------|------|-------|
| (schema not fully documented) | | Used for request/response pair logging |

Query this table when investigating API call payloads. Normalized fields map to `request` and `response`.

---

## Other SQL Tables

| Table | Purpose | When to Use |
|-------|---------|-------------|
| apps_alerts | Application alerts | When investigating alert-triggered issues |
| PriceChangedActivityLogs | Price change audit | When investigating pricing discrepancies |
| accounting_batches | Accounting batch logs | When investigating billing/accounting issues |
| accounting_batches_details | Batch detail logs | Drill-down from accounting_batches |

---

## Compression Formats

### ZIP (services-logs, web-logs)

Each `.zip` file contains a single `.log` file with NDJSON content:
- Archive: `2026-04-02-14.zip`
- Contains: `2026-04-02-14.log`
- Content: NDJSON (one JSON object per line)

### GZIP (openretail)

Each `.log.gz` file is a GZIP-compressed NDJSON file:
- File: `2026-04-02-14.log.gz`
- Decompresses to: NDJSON stream
- Content: One JSON object per line

### Uncompressed (SMB network share)

Files on the network share are plain text:
- `.log` files: May be NDJSON or NLog CSV (tab-delimited)
- `.txt` files: Usually plain text or NLog CSV
- Detect format by checking first line for JSON (`{`) or tab-delimited structure
