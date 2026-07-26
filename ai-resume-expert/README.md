# AI Resume Expert

`ai-resume-expert` 是面向中国大陆技术岗位的开源 AI 程序员简历专家 Skill。它不只是润色句子，而是把用户描述、授权代码/文档、原简历和可选 JD 合并成可追溯的职业事实，再生成岗位定向 Markdown 简历；用户确认后，可在本地生成 PDF、完成自动技术验收，并由用户进行最终视觉签收。

## 它能做什么

- 根据自然语言描述生成程序员简历，并用对话补齐个人角色、技术行动和真实结果。
- 在明确授权后静态读取本地代码库和项目文档，提取项目事实与候选贡献线索。
- 诊断纯文本、Markdown、DOCX 和文本型 PDF 原简历，区分致命、重大和一般问题。
- 在用户明确要求时保留原稿，生成修改对照与独立优化稿。
- 合并用户描述、代码/文档、原简历和 JD，处理重复、冲突与保密披露。
- 没有 JD 时生成岗位基准版；有 JD 时生成只使用证据化关键词的定制版。
- 给出项目入选建议、证据追踪表和面试可辩护性追问。
- 在 Markdown 明确确认后，本地生成单栏、1～2 页、现代技术型极简 PDF，生成页面预览并执行自动技术验收；只有得到用户明确视觉签收的 PDF 才可交付。
- 经用户选择后，把已确认事实保存到 Skill 包以外的本地职业证据库，供下一份 JD 复用。

## 首版支持范围

深度支持中文简历和中国大陆招聘语境中的：

- 后端工程
- 前端、全栈、桌面客户端、iOS、Android 与跨端/移动端
- 测试开发与质量工程
- DevOps、SRE、云工程与平台工程
- 数据工程与数据平台
- 算法、机器学习、AI 工程与 LLM / RAG / Agent 应用
- 技术负责人、技术 Lead 与架构师

产品、项目管理、UI/UX、纯技术支持、硬件电子、销售、市场、人力、纯管理及其他职业只有在用户明确点名本 Skill 时才提供有限的事实整理和通用诊断，不声称职业专家优化或投递就绪。首版也不提供海外市场专家适配。

## 安装

把整个目录复制或链接到 Agent 的 skills 目录。以 Codex 的常见目录为例：

```bash
cp -R ai-resume-expert ~/.codex/skills/
```

不同 Agent 的安装目录可能不同，以所用工具文档为准。`ai-resume-expert/` 顶层目录是开源源码；不要修改仓库里的 `.agents/`、`.agent/`、`.claude/` 或 `.pi/` 运行态副本。

Skill 的专业判断由当前 Agent / 大模型执行，因此“大模型可用”是必要条件；网络不是核心流程的必要条件，也不需要额外模型 API Key。

随附脚本要求 **Python 3.10+**。只生成 Markdown 或可打印 HTML 时，Python 标准库即可；PDF 渲染和自动验收是按需安装的本地能力。

## 最快开始

可以直接说：

> 我要申请 Java 高级后端工程师，没有具体 JD。我做过订单履约和对账任务治理，请你帮我生成简历；信息不够时一次只问一个最关键的问题。

如果没有说目标岗位，Skill 会先只问目标岗位。目标岗位明确后，它会继续确认目标职级、职业阶段和最影响简历质量的事实，不会一上来朗读固定问卷。

更多虚构示例见 [`examples/ai_resume_expert`](../examples/ai_resume_expert/README.md)。

## 四种输入模式

### 1. 直接描述生成

告诉 AI 你在哪家公司、做过什么项目、实际角色、关键行动、技术方案和结果。不会要求你先学会 STAR；AI 会从自然描述中整理 STAR 证据。没有可靠数字时可使用真实定性结果，不会编造“提升 300%”。

### 2. 代码 / 文档辅助

指定有权处理的本地代码库或文档范围。Skill 会先提示平台数据处理边界并请求授权，然后做静态只读分析。默认跳过密钥、`.env`、证书、个人数据、依赖、构建产物、二进制和数据转储，并输出扫描覆盖声明。

代码中存在某项能力只能证明“项目有这项能力”，不能证明“你做了它”。AI 会把可能的个人贡献作为候选方向逐项向你确认。

读取仓库不包含以下权限：

- 执行代码、构建、测试、脚本或容器
- 网络访问
- 读取 Git 历史
- 扫描指定范围以外的目录

这些操作如果确有需要，必须分别获得明确授权。

### 3. 原简历诊断或优化

- **诊断模式**：只列出致命、重大、一般问题，每项说明位置、依据、影响和修改方向；不会擅自重写。
- **优化模式**：保留原文件，先确认事实，再交付修改对照和独立 Markdown 初稿。

支持纯文本、Markdown、DOCX 和文本型 PDF。DOCX 文本提取会读取正文以及直接页眉/页脚 XML，并清楚标注覆盖范围；这仍不能证明其在某一页的可见位置或视觉版式。扫描 PDF、图片或截图只有在 OCR / 视觉能力可用时才能识别，识别文本要由用户确认。不能渲染页面时只称为“文本诊断”，不假装审查了版式。学术 CV、求职信、LinkedIn、个人网站、职位搜索/投递和纯格式转换不在本 Skill 范围内。

### 4. 混合模式

可以同时使用用户描述、授权代码/文档、原简历和 JD。相同事实会去重，不同来源的互斥说法会被阻断并请用户澄清。JD 只改变事实的选择和表达，不会反向污染长期职业事实。

## 生成流程与门槛

1. 明确一个目标岗位、目标职级和职业阶段。
2. 判断模式；私有材料先完成授权。
3. 整理项目事实、用户确认事实、待确认素材、信息缺口、冲突和证据差距。
4. 一次询问一个最关键问题；用户也可要求批量结构化问卷。
5. 对多个项目给出 2～4 个入选建议、排序和淘汰理由，由用户决定。
6. 达到最低证据门槛后才生成完整 Markdown 初稿。
7. 自审事实、岗位、STAR、重复、篇幅、保密和面试可辩护性。
8. 用户确认事实、披露、联系方式和定稿后，才生成 PDF。

完整初稿至少需要：目标岗位与职级、基本时间线，以及每段入选经历中已确认的个人角色、关键行动/技术方案和真实结果；核心技能需有经历支撑，并且没有未解决冲突或保密阻断。信息不足时只交付素材清单、缺口和骨架，不会把占位符集合称作初稿。

## 可能得到的产物

根据模式和阶段，输出以下适用子集：

- 简历素材清单与信息缺口
- 项目入选建议及淘汰理由
- 原简历审查报告
- JD 要求覆盖（已证实 / 部分证实 / 未证实 / 不相关）
- 修改对照（原文 / 改后 / 原因 / 证据）
- Markdown 初稿
- 证据追踪表
- 面试可辩护性追问
- 已通过自动技术验收且得到用户视觉签收的 PDF
- 可选职业证据库更新

证据表、审查理由和面试问题不会混进正式简历正文。

## PDF 设计、本地依赖与降级

### Markdown 是权威源文件

本 Skill 不把 PDF 当作另一份需要手工维护的简历。流程始终是：**已确认 Markdown → 独立、可打印 HTML → PDF**。Markdown 是权威源文件；HTML 和 PDF 都是由它派生的交付物。每个已交付 PDF 都应保留与之对应的 Markdown，单独复验 PDF 时也必须提供该源文件，才能检查源文与 PDF 的一致性。

因此，先生成 Markdown 再转 PDF 正是本 Skill 的正常流程，并不要求把 Markdown 先转成 Word 或手工编辑 PDF。最后一步仍需要一个本地排版/渲染引擎，因为 Markdown 本身不定义 A4 分页、字体嵌入和链接注释。

### 是否需要额外 Codex Skill 或插件？

**不需要。**生成和审核 Markdown、生成可打印 HTML，使用 `ai-resume-expert` 本身及其随附 Python 脚本即可；不需要安装名为 `pdf` 的 Codex Skill、浏览器插件或第三方在线转换插件。职业判断仍由当前 Agent / 大模型完成。

最终 PDF 的依赖是本机可执行程序，而不是另一个 Agent Skill：

| 层级 | 本地能力 | 何时需要 |
|---|---|---|
| PDF 渲染 | **LibreOffice / `soffice`（优先）**；**WeasyPrint / `weasyprint`（备用）** | 需要从可打印 HTML 生成 PDF 时，二者任一可用即可。工具先尝试 LibreOffice；未安装或渲染失败时会尝试 WeasyPrint。 |
| 完整自动验收 | Poppler：`pdfinfo`、`pdftotext`、`pdftoppm`、`pdffonts` | 要获得 `automatic_qualified=true` 并进入 `visual_signoff_pending` 状态时，四项都需要。 |
| 最终交付签收 | 用户查看生成的彩色、灰度页面预览后明确确认 | 不需要额外插件或云服务；签收记录会绑定 PDF、Markdown 和预览文件的哈希。 |

不会上传简历、调用云端转换服务，也不需要 API key。不要因为 LibreOffice 不可用或本机安装异常，就把“重装 LibreOffice”当作唯一前置条件：可用的 WeasyPrint 是本地备用路径。

### macOS 安装示例

下面只在需要交付 PDF 时安装；若只需要 Markdown 或可打印 HTML，无须安装这些组件。Homebrew 安装的 LibreOffice 和 Poppler 组合：

```bash
brew install --cask libreoffice
brew install poppler
```

如果不想使用或暂时无法使用 LibreOffice，可在隔离的 Python 虚拟环境中安装 WeasyPrint；不要为了本 Skill 修改系统 Python。以下命令从仓库根目录运行，安装的是随源码固定的可选 PDF 依赖：

```bash
# WeasyPrint 在 macOS 上需要的原生排版库；已安装时可跳过。
brew install cairo pango gdk-pixbuf libffi

python3 -m venv .venv-ai-resume-expert
. .venv-ai-resume-expert/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ai-resume-expert/requirements-pdf.txt
export PATH="$PWD/.venv-ai-resume-expert/bin:$PATH"

brew install poppler
```

确认命令可被当前终端和 Agent 找到：

```bash
soffice --headless --version       # 使用 LibreOffice 时
weasyprint --version               # 使用 WeasyPrint 时
pdfinfo -v
pdftotext -v
pdftoppm -v
pdffonts -v
```

macOS 通常自带可用于中文排版的系统字体；在其他系统或精简镜像中，请额外确保有可嵌入的中文字体。安装完成后重启 Agent 或让其继承上述 `PATH`，再运行渲染命令。若 WeasyPrint 的安装报缺少系统动态库，请先确认上述 Homebrew 依赖已安装，并参考所安装 WeasyPrint 版本的官方 macOS 说明。

如果 Homebrew 的 LibreOffice 安装后 `soffice` 仍不在 `PATH`，把应用内可执行目录加入当前终端的 `PATH` 后再重启 Agent；这不等于重装 LibreOffice：

```bash
export PATH="/Applications/LibreOffice.app/Contents/MacOS:$PATH"
```

### Ubuntu 24.04 安装示例

Ubuntu 上可用 WeasyPrint 作为首选的可重复路径；以下示例安装 Poppler、中文字体与 WeasyPrint 所需的本地排版库。只有需要 PDF 时才执行：

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-venv fontconfig poppler-utils fonts-noto-cjk \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
  libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info

python3 -m venv .venv-ai-resume-expert
. .venv-ai-resume-expert/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ai-resume-expert/requirements-pdf.txt
export PATH="$PWD/.venv-ai-resume-expert/bin:$PATH"
```

如需保留 LibreOffice 作为优先渲染器，可额外安装 `libreoffice`；它不是 WeasyPrint 路径的前置条件。其他 Linux 发行版或精简镜像属于尽力支持：先确保有等价的 Cairo、Pango、GDK-PixBuf、中文字体和 Poppler 工具，再按对应发行版的软件包名称安装。安装后用前述 `weasyprint --version` 与 Poppler 命令确认当前 Agent 可见。

默认 PDF 是现代技术型极简风：A4 单栏、清晰字体层级、统一对齐和留白、细分隔线、克制深蓝/深灰强调色；正文文字可选择，阅读顺序稳定，链接可点击并可黑白打印。它不会使用双栏主体、技能进度条、复杂图表、花哨背景或隐藏关键词。

最终 Markdown 使用稳定的基础子集：标题、段落、一级列表、加粗、斜体、行内代码、标准链接和分隔线。表格、嵌套列表、图片、原始 HTML 与引用块会先改写为这些结构，避免未经支持的复杂版式在本地 PDF 中静默退化。

默认生成目录是当前工作目录下的 `reports/ai-resume-expert/`。每次生成使用独立版本子目录，保留 Markdown、可打印 HTML、PDF、验收报告、彩色/灰度页面预览和（如已确认）视觉签收 JSON；不会再创建 `output/`。联系方式中的 GitHub、技术博客和个人主页使用短标签链接，避免裸 URL 破坏页首排版。

PDF 从生成到可交付必须经过三个门槛：

1. 用户明确确认 Markdown、披露内容和完整联系方式。
2. 本地渲染完成后，使用源 Markdown 和 Poppler 自动检查中文字体、1～2 页、分页、截断、重叠、链接、孤行与整体可读性。
3. 用户逐页查看彩色和灰度预览后，明确确认默认视觉风格和本次 PDF 可以交付。

PDF 使用本地转换能力，不上传第三方在线服务。技术检查通过且提供对应 Markdown 时，工具只会给出 `visual_signoff_pending`：`automatic_qualified=true`，但 `qualified=false`、`delivery_blocked=true`。这表示 PDF 的结构和渲染检查通过，**不表示用户已经认可视觉效果，也不能交付**。`visual_signoff_pending` 的 CLI 退出码可以是 `0`，因为自动检查本身成功；自动化流程必须读取 JSON 的 `qualified` 和 `delivery_blocked` 决定是否交付，不能只看退出码。Agent 可以协助解读预览，但不能自行替用户签收。

用户明确确认后，才可记录签收，并再次校验签收记录：

```bash
python3 ai-resume-expert/scripts/record_pdf_visual_signoff.py \
  --validation-report reports/ai-resume-expert/<version>/final-resume.validation.json \
  --output reports/ai-resume-expert/<version>/final-resume.visual-signoff.json \
  --confirmed-by-user

python3 ai-resume-expert/scripts/validate_pdf.py final-resume.pdf \
  --source-markdown final-resume.md \
  --visual-signoff reports/ai-resume-expert/<version>/final-resume.visual-signoff.json
```

签收 JSON 包含确认时间及 PDF、Markdown、彩色/灰度预览的路径和哈希。PDF 或 Markdown 的哈希/大小变化，或任一预览的页序号、哈希或大小变化，都会使旧签收失效，必须重新检查并取得新的明确确认；相同页面内容在新的复验目录中生成，仅路径变化不会使签收失效。单独复验已有 PDF 时，必须传入对应的 `--source-markdown final-resume.md`：省略它只会得到 `automatic_checks_only`，不能进入视觉签收；传入源稿但未提供有效 `--visual-signoff` 时只会得到 `visual_signoff_pending`。只有源稿、自动检查和有效签收三者同时成立，结果才是 `qualified=true`、`delivery_blocked=false`。

如果两种本地渲染器都不可用或都失败，仍会保留最终 Markdown 与可打印 HTML，并明确说明 **PDF 没有生成**。如果 PDF 已生成但缺少任一 Poppler 验收工具，则该 PDF 只能是未完全验收的中间文件，不能称为投递就绪；此时同样以 Markdown 与可打印 HTML 作为明确的合格降级交付物。

仓库的 PDF QA 会在 Ubuntu 中安装 WeasyPrint、Poppler 和中文字体，并运行真实渲染与自动检查。这证明 CI 中的渲染栈可用，但不替代任何一份用户简历的逐页视觉确认；也不代表当前本机已经完成真实 PDF 验收。

常见本地能力包括 LibreOffice、WeasyPrint 和 Poppler（`pdfinfo`、`pdftotext`、`pdftoppm`、`pdffonts`）。运行前可查看脚本帮助：

```bash
python3 ai-resume-expert/scripts/render_resume.py --help
python3 ai-resume-expert/scripts/validate_pdf.py --help
python3 ai-resume-expert/scripts/record_pdf_visual_signoff.py --help
```

通常无需传输出目录；如要覆盖默认位置，只能选择 Skill 包以外的用户目录：

```bash
python3 ai-resume-expert/scripts/render_resume.py final-resume.md
```

## 确定性工具

随 Skill 提供的 Python 工具只负责安全扫描、提取、结构校验、持久化和渲染；它们不会取代大模型的职业判断。核心工具只依赖 Python 标准库和明确探测到的本地命令；可选 WeasyPrint PDF 路径使用 `requirements-pdf.txt`。

在构造工具输入前先阅读 [`schemas/README.md`](schemas/README.md)。它提供证据记录、追踪表、Markdown/PDF 门槛包和职业证据库的最小有效 JSON；不要自行猜测字段，也不要把扫描得到的项目事实直接改成个人贡献。

```bash
python3 ai-resume-expert/scripts/scan_repository.py --help
python3 ai-resume-expert/scripts/extract_resume.py --help
python3 ai-resume-expert/scripts/validate_resume_package.py --help
python3 ai-resume-expert/scripts/career_store.py --help
python3 ai-resume-expert/scripts/render_resume.py --help
python3 ai-resume-expert/scripts/validate_pdf.py --help
python3 ai-resume-expert/scripts/record_pdf_visual_signoff.py --help
```

不要把脚本的“运行成功”等同于简历内容已经专业、真实或投递就绪；最终内容仍需 Agent 自审和用户确认。

## 隐私与真实性

- 真实简历、公司代码、生成物、PDF 视觉签收记录和职业证据库不要提交到本开源仓库。
- 职业证据库默认不创建；只有用户明确选择并指定 Skill 包外路径时才写入。
- 职业证据库不保存源码、密钥、无关公司资料、原简历全文或某个 JD 的包装文案。
- 内部项目名、客户、域名、接口、表名和安全配置应删除、泛化或阻断。
- 所有强陈述都应能继续讲清背景、个人作用、方案取舍和结果依据。

## 不做什么

首版不生成求职信，不优化 LinkedIn 或个人网站，不制作作品集网站或学术 CV，不搜索职位、不抓取招聘网站、不自动投递，也不提供 ATS 通过、面试或录用保证。面试能力仅限验证简历中的核心陈述是否可辩护。

## 开发与验证

仓库级样例、测试和行为评测分别位于 `examples/ai_resume_expert/`、`tests/ai_resume_expert/` 和 `evals/ai_resume_expert/`，不放入安装态 Skill 目录。

```bash
python3 scripts/check_all_skills.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

GitHub Actions 除基础测试外还会运行真实 WeasyPrint/Poppler 的 PDF QA；它只验证自动验收契约，不能代替用户签收。

本项目使用 MIT License。输出质量取决于用户提供并确认的事实以及当前 Agent 的能力；“投递就绪”表示通过本 Skill 的事实、岗位、保密、可辩护性、PDF 自动门槛以及用户明确视觉签收，不代表一定通过任何 ATS 或获得面试。
