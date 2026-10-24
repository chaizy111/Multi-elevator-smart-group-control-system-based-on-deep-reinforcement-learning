# 提交与材料工具

启动、环境和质量工具保留在scripts根目录；材料生成器放在scripts/materials，与项目运行依赖分离，见[材料说明](../../scripts/materials/README.md)。

`package_submission.py`从已提交、无已跟踪差异的main生成`submission/多电梯群控_源码与作业材料.zip`，加入已构建的frontend/dist。包内SUBMISSION.json记录源码提交和前端文件SHA；包中保留源码、四份注册模型、真实曲线、报告、PPT及截图，排除依赖安装、缓存、Git内部数据和大型历史实验。它只读取Git，不自动暂存、提交或推送。

在项目根执行，先完成质量检查与提交，再生成包：

```bash
source scripts/project_env.sh
npm --prefix frontend run build
.venv/bin/python scripts/package_submission.py
```

解压后按根README安装环境及启动，模型安装器从随包资产校验复制，不要求历史artifacts。压缩包由最终提交树生成，因此新文件应先纳入提交，避免遗漏；Git分支备份与原始研究档案的边界见[冻结说明](../release/README.md)。

仓库通过.gitattributes把PDF、Word、PPTX与PyTorch权重声明为二进制，避免Git对内部格式进行文本换行或空白修复。真实训练CSV保留原CRLF与SHA，只允许其原生行尾，其他空白仍检查。
