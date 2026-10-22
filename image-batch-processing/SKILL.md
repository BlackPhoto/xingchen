---
name: image-batch-processing
description: "Batch image operations on Windows when Python image libraries (PIL/OpenCV) are unavailable and pip is blocked. Inspect dimensions, resize, crop, and content-aware square-cropping of QR code images using PowerShell + System.Drawing (.NET built-in, zero dependencies). Also covers Excel COM read/write of .xls/.xlsx tables and VLM image-to-table backfill workflows in the same zero-dependency environment. Use for recurring folder-based image tasks: badge/ID photo and QR code processing, cropping QR screenshots to square, batch verification, and extracting totals/category amounts from dated receipt photos into ledger spreadsheets."
name_cn: 批量图像处理
description_cn: "无Python图像库的Windows环境：PowerShell+System.Drawing批量处理图片（缩放裁切、二维码定位裁方）；含Excel COM读写表格与视觉模型识别单据照片回填台账，适合工号牌、二维码、送货单台账等周期任务。"
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'e4538fb7-d7fd-4c51-8384-783f244e4e24'
  PropagateID: 'e4538fb7-d7fd-4c51-8384-783f244e4e24'
  ReservedCode1: '746d30f4-95a6-4652-8198-2b91dd6bde4f'
  ReservedCode2: '746d30f4-95a6-4652-8198-2b91dd6bde4f'
---

# 批量图像处理（Windows / 无 Python 图像库）

## 适用场景
- 批量处理目录下的图片：尺寸检查、缩放、裁切、保持原格式保存
- 典型周期性任务：工号牌/证件照/二维码图片整理，如"把含二维码的长截图/海报裁成仅含二维码的正方形"
- 环境约束：Python 缺少 PIL/OpenCV 且 pip 安装被网络策略阻断（WinError 10013/10053）时，不要反复重试安装，直接改用 PowerShell + System.Drawing（.NET 内置，零依赖）
- 边界：有 Python/openpyxl 可用时，表格类工作流优先走 xlsx 技能；本技能管图像本身的批量处理，以及无 Python 库环境下的 Excel COM 表格读写与"图片识别→回填表格"工作流（xlsx 技能的 openpyxl/LibreOffice 路线在此环境不可用）

## 核心模式：PowerShell + System.Drawing

```powershell
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($path)      # 会锁文件，用完必须 Dispose
$w = $img.Width; $h = $img.Height

# 缩小（分析用，Bilinear 插值）
$small = New-Object System.Drawing.Bitmap($sw, $sh)
$g = [System.Drawing.Graphics]::FromImage($small)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::Bilinear
$g.DrawImage($img, 0, 0, $sw, $sh); $g.Dispose()

# 裁切（源/目标矩形 + Pixel 单位）
$crop = New-Object System.Drawing.Bitmap($side, $side)
$g2 = [System.Drawing.Graphics]::FromImage($crop)
$g2.DrawImage($img, (New-Object System.Drawing.Rectangle(0,0,$side,$side)),
              (New-Object System.Drawing.Rectangle($x,$y,$side,$side)), [System.Drawing.GraphicsUnit]::Pixel)
$g2.Dispose()
$fmt = $img.RawFormat        # 先取原格式再 Dispose
$img.Dispose()
$crop.Save($outPath, $fmt)   # jpg 存 jpg、png 存 png，勿统一存 Jpeg
$crop.Dispose()
```

### 坑位
- `FromFile` 锁定文件：原地覆盖保存前必须先 `$img.Dispose()`；分析用的小图也要 Dispose
- 保存格式用 `$img.RawFormat`，否则 .png 文件内容会被存成 JPEG
- `GetPixel` 逐像素很慢：先缩到最长边约 300px 再做像素级分析
- 含中文的 .ps1 必须存为 UTF-8 with BOM，否则 Windows PowerShell 按 ANSI 解析导致中文乱码 + ParserError；用 `[IO.File]::WriteAllText($p, $c, [Text.UTF8Encoding]::new($true))` 写盘
- 执行策略拦截时用 `powershell -ExecutionPolicy Bypass -File xxx.ps1`
- 原地覆盖不可逆：先复制到工作目录再裁切副本，或先备份原目录

## 旗舰技术：二维码裁正方形（方差定位算法）

来源图片布局各异（手机长截图 9:16~9:20、微信名片 3:4、近方形纯码图），二维码位置与占比差异极大，固定比例裁切不可行，需自动定位：

1. 加载图片，缩到最长边约 300px 降低计算量
2. 逐像素灰度：`gray = (r*299 + g*587 + b*114) / 1000`
3. 计算每行、每列的灰度方差：二维码黑白点阵密集，其行/列方差显著高于纯色背景与平滑渐变区
4. 取方差 ≥ 最大方差 40% 的行区间与列区间 → 二维码包围盒
5. 按长短边扩成正方形，四周再加约 5% 边距，确保三个回字形定位角完整
6. 坐标按缩放比例映射回原图裁切，按原格式保存
7. 已是正方形的文件跳过并计数

实测 98 张布局各异的二维码图：97 张一次裁切成功、1 张原已正方形跳过；裁后抽样用视觉模型验证定位角完整、无截断。

完整可运行脚本：`scripts/qr-crop-square.ps1`（参数化：目录、文件过滤、方差阈值、边距比例）。

## 批量操作通用清单
- [ ] 处理前后文件数对账，跳过/失败项单独列出报告
- [ ] 不可逆操作前先备份，或先在副本目录上执行
- [ ] 抽样 3–5 张用视觉模型验证（是否截断、内容是否完整）
- [ ] 定位失败的文件降级处理：明确报告交人工确认，勿静默跳过

## Windows 无 Python 库环境：Excel COM 读写 .xls/.xlsx

Python 缺 openpyxl/pandas 且 pip 被网络策略阻断时，用 PowerShell + Excel COM 处理表格（零依赖）：

```powershell
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false; $excel.DisplayAlerts = $false
$wb = $excel.Workbooks.Open("E:\路径\文件.xls")
$ws = $wb.Worksheets.Item("sheet名")     # 中文 sheet 名直接用字符串
$v = $ws.Cells.Item($r,$c).Text          # 读显示文本；.Formula 读公式；.Value2 读原始值
$ws.Cells.Item($r,$c).Value = 123.45     # 写入
$wb.Save(); $wb.Close($false); $excel.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
```

### 坑位
- 后台模式（`Visible=$false`）禁止调用 `Range.Activate()`：抛"不能取得类 Range 的 Activate 属性"，且异常会连带同批后续赋值静默丢失；直接 `Range.Value` 赋值即可
- 批量写入后必须逐格读回验证（`Value2` 回读比对），不能只信脚本输出：COM 偶发 `InvalidCastException` 时赋值实际未生效，需对失败格重试
- 读公式列时用 `.Formula` 判断（如 `=C2+F2`），避免误把公式列当空列覆盖；只填空白格的任务先读回再写
- 含中文路径/内容的 .ps1 必须存为 UTF-8 with BOM 再用 `-File` 执行（见上文坑位）
- COM 进程要 Quit + ReleaseComObject，否则 Excel 进程残留锁文件

## 识别图片内容回填表格（VLM 提取 → 只填空白格）

周期性任务常见形态：目录下按日期命名的单据照片（如 `20260901城中.jpg`），需提取合计金额、分类金额（水果等）回填台账。方法：

1. 先读表建立"日期列 → 行"映射，再列目录图片建立"文件名日期 → 表行"映射；无对应图片的行保持空白
2. 逐张用视觉模型提取，prompt 固定输出 3 项（合计/目标分类金额/特殊标记项），无则答"无"，便于批量解析
3. 写入前先备份原文件到 `.temp`；只填空白单元格，已有数据一律不动，公式列（`=C+F` 之类）绝不覆盖
4. 写入后逐格读回验证（见 Excel COM 坑位）
5. 用 processed_log.json 记录已处理文件（文件名+mtime），下次只处理新增/变更图片
6. 特殊标记项（如菜品名带"/"）单独回填到指定列，格式先向用户确认（只填金额数字还是"名称+金额"）

### 坑位
- 文件名日期与表内日期格式可能不一致（表内 `9.1O` 字母 O 当 0、`9.31` 实为 10.1 笔误、跨月表日期延续到下月），映射时按行序+上下文核对，勿只做字符串匹配
- 单张图片中多项同类金额（两种水果）需相加；边界品类（红枣算水果还是干货）先用视觉模型确认归类再计入
- 表内已有数据与图片识别值不一致时，遵守"只填空白"约定不覆盖，差异单独报告