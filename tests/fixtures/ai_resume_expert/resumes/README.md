# 脱敏原简历 fixture

- `sample_resume.md` 与 `sample_resume.txt`：可直接用于文本提取和诊断评测。
- `sample_resume.pdf`：可由本地 `pdftotext` 提取的一页 ASCII 文本型 PDF，可直接用于 PDF 输入评测。
- `docx-document.xml`、`docx-header1.xml` 和 `docx-footer1.xml`：`sample_resume.docx` 的脱敏 WordprocessingML 等价载荷。契约测试在临时目录中用标准库 `zipfile` 将其封装为 DOCX，避免在源码补丁中维护不透明二进制 ZIP；生成文件不会写入仓库。

所有姓名、学校、公司和经历均为虚构内容。
