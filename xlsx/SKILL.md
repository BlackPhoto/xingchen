---
name: xlsx
description: "Comprehensive spreadsheet creation, editing, and analysis with support for formulas, formatting, data analysis, and visualization. When Claude needs to work with spreadsheets (.xlsx, .xlsm, .csv, .tsv, etc) for: (1) Creating new spreadsheets with formulas and formatting, (2) Reading or analyzing data, (3) Modify existing spreadsheets while preserving formulas, (4) Data analysis and visualization in spreadsheets, or (5) Recalculating formulas"
name_cn: "Excel表格助手"
description_cn: "支持创建、编辑和整理Excel、CSV 等表格文件，可用于数据录入、公式计算、格式调整、图表制作和数据清洗，适合把零散数据整理成规范、可直接使用的电子表格。"
license: Proprietary. LICENSE.txt has complete terms
---

# Requirements for Outputs

## All Excel files

### Zero Formula Errors
- Every Excel model MUST be delivered with ZERO formula errors (#REF!, #DIV/0!, #VALUE!, #N/A, #NAME?)

### Preserve Existing Templates (when updating templates)
- Study and EXACTLY match existing format, style, and conventions when modifying files
- Never impose standardized formatting on files with established patterns
- Existing template conventions ALWAYS override these guidelines

## Template Compliance Policy

### Header Row Protection (Excel-Specific Rule)

When working with an existing Excel file or a user-provided template, you are PROHIBITED from modifying header rows unless the user explicitly grants permission. Only data rows may be modified. "Header rows" = any rows defining column names or field labels (typically the first row, or the first few frozen rows).

```
表头行（禁止修改）: | 姓名 | 部门 | 入职日期 | 薪资（元） |
数据行（允许修改）: | 张三 | 技术部 | 2024-01-15 | 15000 |
                  | 李四 | 市场部 | 2023-06-20 | 12000 |
```

If preserving headers makes it impossible to fulfill the user's requirements, describe the specific conflict and obtain explicit consent before modifying. Do NOT silently modify headers or template structure.

**Example:** "您的需求需要新增「绩效等级」列，请问是否允许在现有表头末尾新增该列？"

## Financial models

### Color Coding Standards
Unless otherwise stated by the user or existing template

#### Industry-Standard Color Conventions
- **Blue text (RGB: 0,0,255)**: Hardcoded inputs, and numbers users will change for scenarios
- **Black text (RGB: 0,0,0)**: ALL formulas and calculations
- **Green text (RGB: 0,128,0)**: Links pulling from other worksheets within same workbook
- **Red text (RGB: 255,0,0)**: External links to other files
- **Yellow background (RGB: 255,255,0)**: Key assumptions needing attention or cells that need to be updated

### Number Formatting Standards

#### Required Format Rules
- **Years**: Format as text strings (e.g., "2024" not "2,024")
- **Currency**: Use $#,##0 format; ALWAYS specify units in headers ("Revenue ($mm)")
- **Zeros**: Use number formatting to make all zeros "-", including percentages (e.g., "$#,##0;($#,##0);-")
- **Percentages**: Default to 0.0% format (one decimal)
- **Multiples**: Format as 0.0x for valuation multiples (EV/EBITDA, P/E)
- **Negative numbers**: Use parentheses (123) not minus -123

### Formula Construction Rules

#### Assumptions Placement
- Place ALL assumptions (growth rates, margins, multiples, etc.) in separate assumption cells
- Use cell references instead of hardcoded values in formulas
- Example: Use =B5*(1+$B$6) instead of =B5*1.05

#### Formula Error Prevention
- Verify all cell references are correct
- Check for off-by-one errors in ranges
- Ensure consistent formulas across all projection periods
- Test with edge cases (zero values, negative numbers)
- Verify no unintended circular references

#### Documentation Requirements for Hardcodes
- Comment or in cells beside (if end of table). Format: "Source: [System/Document], [Date], [Specific Reference], [URL if applicable]"
- Examples:
  - "Source: Company 10-K, FY2024, Page 45, Revenue Note, [SEC EDGAR URL]"
  - "Source: Company 10-Q, Q2 2025, Exhibit 99.1, [SEC EDGAR URL]"
  - "Source: Bloomberg Terminal, 8/15/2025, AAPL US Equity"
  - "Source: FactSet, 8/20/2025, Consensus Estimates Screen"

# XLSX creation, editing, and analysis

## Overview

A user may ask you to create, edit, or analyze the contents of an .xlsx file. You have different tools and workflows available for different tasks.

## Important Requirements

**LibreOffice Required for Formula Recalculation**: You can assume LibreOffice is installed for recalculating formula values using the `recalc.py` script. The script automatically configures LibreOffice on first run

## Reading and analyzing data

### Data analysis with pandas
For data analysis, visualization, and basic operations, use **pandas** which provides powerful data manipulation capabilities:

```python
import pandas as pd

# Read Excel
df = pd.read_excel('file.xlsx')  # Default: first sheet
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # All sheets as dict

# Analyze
df.head()      # Preview data
df.info()      # Column info
df.describe()  # Statistics

# Write Excel
df.to_excel('output.xlsx', index=False)
```

## Excel File Workflows

## CRITICAL: Use Formulas, Not Hardcoded Values

**Always use Excel formulas instead of calculating values in Python and hardcoding them.** This ensures the spreadsheet remains dynamic and updateable.

### ❌ WRONG - Hardcoding Calculated Values
```python
# Bad: Calculating in Python and hardcoding result
total = df['Sales'].sum()
sheet['B10'] = total  # Hardcodes 5000

# Bad: Computing growth rate in Python
growth = (df.iloc[-1]['Revenue'] - df.iloc[0]['Revenue']) / df.iloc[0]['Revenue']
sheet['C5'] = growth  # Hardcodes 0.15

# Bad: Python calculation for average
avg = sum(values) / len(values)
sheet['D20'] = avg  # Hardcodes 42.5
```

### ✅ CORRECT - Using Excel Formulas
```python
# Good: Let Excel calculate the sum
sheet['B10'] = '=SUM(B2:B9)'

# Good: Growth rate as Excel formula
sheet['C5'] = '=(C4-C2)/C2'

# Good: Average using Excel function
sheet['D20'] = '=AVERAGE(D2:D19)'
```

This applies to ALL calculations - totals, percentages, ratios, differences, etc. The spreadsheet should be able to recalculate when source data changes.

## Common Workflow
1. **Choose tool**: pandas for data, openpyxl for formulas/formatting
2. **Create/Load**: Create new workbook or load existing file
3. **Modify**: Add/edit data, formulas, and formatting
4. **Save**: Write to file
5. **Recalculate formulas (MANDATORY IF USING openpyxl AND FORMULAS)**: Use the recalc.py script. Skip this step if the file was generated with XlsxWriter (cached values included natively)
   ```bash
   python recalc.py output.xlsx
   ```
6. **Verify and fix any errors**:
   - The script returns JSON with error details
   - If `status` is `errors_found`, check `error_summary` for specific error types and locations
   - Fix the identified errors and recalculate again
   - Common errors to fix:
     - `#REF!`: Invalid cell references
     - `#DIV/0!`: Division by zero
     - `#VALUE!`: Wrong data type in formula
     - `#NAME?`: Unrecognized formula name

### Creating new Excel files

```python
# Using openpyxl for formulas and formatting
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

# Add data
sheet['A1'] = 'Hello'
sheet['B1'] = 'World'
sheet.append(['Row', 'of', 'data'])

# Add formula
sheet['B2'] = '=SUM(A1:A10)'

# Formatting
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')

# Column width
sheet.column_dimensions['A'].width = 20

wb.save('output.xlsx')
```

### Editing existing Excel files

```python
# Using openpyxl to preserve formulas and formatting
from openpyxl import load_workbook

# Load existing file
wb = load_workbook('existing.xlsx')
sheet = wb.active  # or wb['SheetName'] for specific sheet

# Working with multiple sheets
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    print(f"Sheet: {sheet_name}")

# Modify cells
sheet['A1'] = 'New Value'
sheet.insert_rows(2)  # Insert row at position 2
sheet.delete_cols(3)  # Delete column 3

# Add new sheet
new_sheet = wb.create_sheet('NewSheet')
new_sheet['A1'] = 'Data'

wb.save('modified.xlsx')
```

## Recalculating formulas

Excel files created or modified by openpyxl contain formulas as strings but not calculated values. Use the provided `recalc.py` script to recalculate formulas:

```bash
python recalc.py <excel_file> [timeout_seconds]
```

Example:
```bash
python recalc.py output.xlsx 30
```

> If `python recalc.py ...` fails because `soffice`/LibreOffice is unavailable and you cannot obtain/install it for the current platform, run degraded fallback checks instead:
>
> - `python scripts/fallback_formula_check.py <excel_file> --out <report.json>`
>
> **Limitation**: this is a degraded-mode / best-effort pipeline. The agent MUST explicitly tell the user it is using degraded mode and MUST NOT claim accurate or guaranteed zero-error results. If you need authoritative verification, install `soffice`/LibreOffice and rerun.

The script:
- Automatically sets up LibreOffice macro on first run
- Recalculates all formulas in all sheets
- Scans ALL cells for Excel errors (#REF!, #DIV/0!, etc.)
- Returns JSON with detailed error locations and counts
- Works on Linux, macOS and Windows

## Formula Verification Checklist

Quick checks to ensure formulas work correctly:

### Essential Verification
- [ ] **Test 2-3 sample references**: Verify they pull correct values before building full model
- [ ] **Column mapping**: Confirm Excel columns match (e.g., column 64 = BL, not BK)
- [ ] **Row offset**: Remember Excel rows are 1-indexed (DataFrame row 5 = Excel row 6)

### Common Pitfalls
- [ ] **NaN handling**: Check for null values with `pd.notna()`
- [ ] **Far-right columns**: FY data often in columns 50+
- [ ] **Multiple matches**: Search all occurrences, not just first
- [ ] **Division by zero**: Check denominators before using `/` in formulas (#DIV/0!)
- [ ] **Wrong references**: Verify all cell references point to intended cells (#REF!)
- [ ] **Cross-sheet references**: Use correct format (Sheet1!A1) for linking sheets

### Formula Testing Strategy
- [ ] **Start small**: Test formulas on 2-3 cells before applying broadly
- [ ] **Verify dependencies**: Check all cells referenced in formulas exist
- [ ] **Test edge cases**: Include zero, negative, and very large values

### Interpreting recalc.py Output
The script returns JSON with error details:
```json
{
  "status": "success",           // or "errors_found"
  "total_errors": 0,              // Total error count
  "total_formulas": 42,           // Number of formulas in file
  "error_summary": {              // Only present if errors found
    "#REF!": {
      "count": 2,
      "locations": ["Sheet1!B5", "Sheet1!C10"]
    }
  }
}
```

## Chart Generation

### CRITICAL: Mobile Compatibility Rules for Charts

**Charts generated by openpyxl are invisible on mobile devices** (WeChat Work, WPS Mobile, Excel Mobile). openpyxl chart output lacks data caches (`numCache`/`strCache`), uses `oneCellAnchor` with absolute paths, and leaves formula cells without cached values. Mobile preview engines do not recalculate formulas — the chart gets no data and renders blank. Desktop Excel/WPS auto-recalculate on open, so they appear fine there.

**Follow this decision flow when the output file contains charts:**

| Scenario | Tool | LibreOffice needed? |
|----------|------|-------------------|
| 1. Creating a NEW file with charts | **XlsxWriter** | No |
| 2. Adding charts to an EXISTING file | **openpyxl + recalc.py** | Yes |
| 3. Degraded mode (neither XlsxWriter installable nor LibreOffice available) | openpyxl only | N/A — must warn user |

### Scenario 1: New File — Use XlsxWriter

**When creating a new Excel file that contains charts, ALWAYS use XlsxWriter.** It generates native charts with data caches, correct anchor types (`twoCellAnchor`), relative paths, and formula cached values — everything mobile devices need. Install it first if not present:

```bash
pip install xlsxwriter
```

Example:

```python
import xlsxwriter

workbook = xlsxwriter.Workbook('output.xlsx')
worksheet = workbook.add_worksheet('Sheet1')

# Write data
data = [('销售部', 385, 467), ('市场部', 296, 358)]
num_fmt = workbook.add_format({'num_format': '#,##0'})
pct_fmt = workbook.add_format({'num_format': '0.0%'})

for i, (name, q2, q3) in enumerate(data):
    r = 3 + i
    worksheet.write(r, 0, name)
    worksheet.write_number(r, 1, q2, num_fmt)
    worksheet.write_number(r, 2, q3, num_fmt)
    # Formula WITH cached value (4th argument) — mobile devices read this directly
    worksheet.write_formula(r, 3, f'=C{r+1}-B{r+1}', num_fmt, q3 - q2)
    worksheet.write_formula(r, 4, f'=IF(B{r+1}=0,"",(C{r+1}-B{r+1})/B{r+1})', pct_fmt, (q3-q2)/q2)

# Create native chart
chart = workbook.add_chart({'type': 'column'})
chart.add_series({
    'name': 'Q2季度',
    'categories': ['Sheet1', 3, 0, 3 + len(data) - 1, 0],
    'values': ['Sheet1', 3, 1, 3 + len(data) - 1, 1],
    'fill': {'color': '#4472C4'},
})
chart.add_series({
    'name': 'Q3季度',
    'categories': ['Sheet1', 3, 0, 3 + len(data) - 1, 0],
    'values': ['Sheet1', 3, 2, 3 + len(data) - 1, 2],
    'fill': {'color': '#ED7D31'},
})
chart.set_title({'name': '各部门Q2 vs Q3绩效对比'})
chart.set_x_axis({'name': '部门'})
chart.set_y_axis({'name': '绩效得分'})
chart.set_legend({'position': 'bottom'})
chart.set_size({'width': 831, 'height': 416})

# VERTICAL layout for multiple charts — never side-by-side
worksheet.insert_chart('A12', chart)

workbook.close()
```

**XlsxWriter rules:**
1. Write formulas with cached values: `write_formula(cell, formula, format, cached_value)` — the 4th argument is mandatory for mobile compatibility
2. Multiple charts go at different rows (e.g., `'A12'`, `'A30'`), never side-by-side — mobile screens only show the last chart of a side-by-side pair
3. Chart size: `set_size({'width': 831, 'height': 416})` fits both desktop and mobile
4. Only creates new files — cannot open/modify existing files
5. Unsupported chart types: 3D charts, Bubble, Surface
6. **MANDATORY post-process: fix chart xfrm (position/size) — see below**

### CRITICAL: xfrm Fix — Required After Every XlsxWriter Chart Generation

XlsxWriter writes chart position and size as `0×0` in the drawing XML (`<a:off x="0" y="0"/><a:ext cx="0" cy="0"/>`). Desktop Excel locates charts via cell anchors and ignores xfrm, but **mobile preview engines (WeChat Work, WPS Mobile, Excel Mobile) read xfrm values**:

- `ext = 0×0` → chart renders as nothing on mobile (invisible until the user manually drags it, which rewrites xfrm)
- `off = 0,0` → chart is painted at the top-left of the worksheet, **covering the data area** on mobile

Both defects are verified in real-device testing. Fixing ONLY `ext` is not enough — `off` must also be patched, otherwise charts still cover data.

**Fix options (in priority order):**

```bash
# Option A (preferred): LibreOffice writes authoritative xfrm values
python recalc.py output.xlsx

# Option B (no LibreOffice needed): pure-Python fix, computes real off/ext
# from anchor cells (row heights/column widths, handles hidden rows/cols,
# custom sizes, charts anchored anywhere — verified to match LibreOffice
# within ~6px rounding tolerance)
python fix_chart_xfrm.py output.xlsx
```

**NEVER deliver an XlsxWriter chart file without one of these fixes.** The file looks perfect on desktop Excel but is broken (invisible or misplaced) on mobile.

Note: `fix_chart_xfrm.py` also patches zero-size xfrm for images inserted via `insert_image()`, which suffer the same mobile-invisibility issue.

### Scenario 2: Existing File — Use openpyxl + LibreOffice recalc

When adding charts to an existing file (preserving its formatting, merged cells, templates):

1. Load with openpyxl: `wb = load_workbook('existing.xlsx')`
2. Add charts via openpyxl chart API
3. Save
4. **MANDATORY**: Run `python recalc.py output.xlsx` — this fills formula cached values AND fixes the chart structure (converts `oneCellAnchor` → `twoCellAnchor`, injects `numCache`/`strCache`, fixes paths) so mobile devices can render the charts

Do NOT manually edit the xlsx zip/XML to inject caches — manual zip editing corrupts the file structure for mobile parsers (verified in testing). LibreOffice recalc is the only reliable fix.

If the existing file's structure is simple (no complex formatting/templates), an alternative is: read all data with pandas → rebuild the entire file with XlsxWriter (Scenario 1). Use judgment: preserve original file with openpyxl when it has complex formatting worth keeping.

### Scenario 3: Degraded Mode — openpyxl Only + MUST Warn User

If XlsxWriter cannot be installed (no network) AND LibreOffice is unavailable, generate with openpyxl and **MUST explicitly tell the user BEFORE delivering the file**:

> "需要说明：当前环境无法安装 XlsxWriter，也没有 LibreOffice，本次生成的图表在手机端（企业微信、WPS手机版、Excel手机版）打开时可能无法显示，桌面端 Excel/WPS 不受影响。如果需要手机端正常显示，可以安装 LibreOffice（约几百MB，从 libreoffice.org 下载）后让我重新生成。"

Never silently deliver a chart file in degraded mode. The user must know the mobile limitation upfront.

### Chart Type Reference (XlsxWriter)

| Type | Description |
|------|-------------|
| `column` | Vertical bar chart |
| `bar` | Horizontal bar chart |
| `line` | Line chart |
| `pie` | Pie chart |
| `area` | Area chart |
| `scatter` | Scatter chart |
| `radar` | Radar chart |
| `stock` | Stock chart |
| `doughnut` | Doughnut chart |

## Best Practices

### Library Selection
- **pandas**: Best for data analysis, bulk operations, and simple data export
- **openpyxl**: Best for complex formatting, formulas, and Excel-specific features
- **XlsxWriter**: Required for NEW files containing charts (see "Chart Generation" section)

### Working with openpyxl
- Cell indices are 1-based (row=1, column=1 refers to cell A1)
- Use `data_only=True` to read calculated values: `load_workbook('file.xlsx', data_only=True)`
- **Warning**: If opened with `data_only=True` and saved, formulas are replaced with values and permanently lost
- For large files: Use `read_only=True` for reading or `write_only=True` for writing
- Formulas are preserved but not evaluated - use recalc.py to update values

### Working with pandas
- Specify data types to avoid inference issues: `pd.read_excel('file.xlsx', dtype={'id': str})`
- For large files, read specific columns: `pd.read_excel('file.xlsx', usecols=['A', 'C', 'E'])`
- Handle dates properly: `pd.read_excel('file.xlsx', parse_dates=['date_column'])`

## Code Style Guidelines
**IMPORTANT**: When generating Python code for Excel operations:
- Write minimal, concise Python code without unnecessary comments
- Avoid verbose variable names and redundant operations
- Avoid unnecessary print statements

**For Excel files themselves**:
- Add comments to cells with complex formulas or important assumptions
- Document data sources for hardcoded values
- Include notes for key calculations and model sections
